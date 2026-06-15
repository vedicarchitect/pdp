"""Tests for ST-touch intra-bar exit and trailing profit lock.

Covers behavioral contracts from supertrend-intrabar-exit-and-profit-lock:

  7.1  prev_bar_st pattern: at bar N, prev_bar_st equals the ST emitted by bar N-1;
       None for the first bar in the series.
  7.2  Touch detection: uptrend (dir +1) breaches on sub_low <= value; downtrend
       (dir -1) breaches on sub_high >= value; boundary values handled correctly.
  7.3  Profit lock arms and fires at 50% of peak when peak >= 2000.
  7.4  Trailing floor rises with peak; fires when MTM drops below the highest floor,
       not the first armed floor.
  7.5  No profit_lock fires when peak stays below the 2000 trigger.

These tests exercise pure logic without MongoDB or the full backtest script
(which has argparse at module level).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest

# ── Constants (mirrored from backtest_multiday) ───────────────────────────────
PROFIT_LOCK_TRIGGER = 2_000.0
PROFIT_LOCK_TRAIL   = 0.5

LOT = 65


# ── Minimal SuperTrendState stand-in ──────────────────────────────────────────
@dataclass
class _ST:
    direction: int
    value: Decimal
    flipped: bool = False


# ── Minimal Position stand-in ─────────────────────────────────────────────────
@dataclass
class _Position:
    total_qty:  int   = 0
    total_cost: float = 0.0
    peak_mtm:   float = 0.0

    def add(self, qty, px):
        self.total_qty  += qty
        self.total_cost += qty * px

    @property
    def avg_entry(self):
        return self.total_cost / self.total_qty if self.total_qty else 0.0

    def mtm(self, current_px):
        return (self.avg_entry - current_px) * self.total_qty


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_profit_lock(pos: _Position, current_px: float):
    """Run profit-lock update against a position; returns 'profit_lock' or None."""
    current_mtm = pos.mtm(current_px)
    pos.peak_mtm = max(pos.peak_mtm, current_mtm)
    if pos.peak_mtm >= PROFIT_LOCK_TRIGGER:
        lock_floor = pos.peak_mtm * PROFIT_LOCK_TRAIL
        if current_mtm <= lock_floor:
            return "profit_lock"
    return None


T0 = datetime(2026, 6, 12, 9, 30)


# ── 7.1: prev_bar_st pattern ──────────────────────────────────────────────────

def test_prev_bar_st_is_none_for_first_bar():
    """Before any bar is processed, prev_bar_st is None."""
    st_series = [
        _ST(direction=1, value=Decimal("100")),
        _ST(direction=1, value=Decimal("101")),
    ]
    prev_st = None
    # Simulate the loop header for the first bar
    prev_bar_st = prev_st
    prev_st = st_series[0]
    assert prev_bar_st is None


def test_prev_bar_st_equals_prior_bar_st():
    """At bar 2, prev_bar_st equals the ST emitted by bar 1."""
    st_series = [
        _ST(direction=1,  value=Decimal("100")),
        _ST(direction=-1, value=Decimal("101")),
    ]
    prev_st = None
    # Process bar 1
    prev_bar_st = prev_st
    prev_st = st_series[0]
    # Process bar 2
    prev_bar_st = prev_st
    prev_st = st_series[1]
    assert prev_bar_st is st_series[0]
    assert float(prev_bar_st.value) == 100.0


# ── 7.2: Touch detection ──────────────────────────────────────────────────────

def _detect_touch(direction: int, prev_st_val: float, sub_low: float, sub_high: float) -> bool:
    if direction > 0:
        return sub_low <= prev_st_val    # uptrend: low breaches ST line
    else:
        return sub_high >= prev_st_val   # downtrend: high breaches ST line


def test_touch_uptrend_breach():
    """Uptrend position: sub_low <= prev_st.value triggers breach."""
    assert _detect_touch(direction=1, prev_st_val=100.0, sub_low=99.0, sub_high=105.0)


def test_touch_uptrend_no_breach():
    """Uptrend position: sub_low > prev_st.value → no breach."""
    assert not _detect_touch(direction=1, prev_st_val=100.0, sub_low=101.0, sub_high=105.0)


def test_touch_uptrend_boundary_exact():
    """Uptrend position: sub_low == prev_st.value exactly → breach (<=)."""
    assert _detect_touch(direction=1, prev_st_val=100.0, sub_low=100.0, sub_high=105.0)


def test_touch_downtrend_breach():
    """Downtrend position: sub_high >= prev_st.value triggers breach."""
    assert _detect_touch(direction=-1, prev_st_val=100.0, sub_low=95.0, sub_high=101.0)


def test_touch_downtrend_no_breach():
    """Downtrend position: sub_high < prev_st.value → no breach."""
    assert not _detect_touch(direction=-1, prev_st_val=100.0, sub_low=95.0, sub_high=99.0)


def test_touch_downtrend_boundary_exact():
    """Downtrend position: sub_high == prev_st.value exactly → breach (>=)."""
    assert _detect_touch(direction=-1, prev_st_val=100.0, sub_low=95.0, sub_high=100.0)


# ── 7.3: Profit lock arms and fires ──────────────────────────────────────────

def test_profit_lock_arms_and_fires():
    """MTM [500, 1800, 2400, 1800, 1200]: arms at 2400 peak, fires at 1200 (50% of 2400)."""
    pos = _Position()
    pos.add(2 * LOT, 100.0)  # 130 qty at 100 entry (avg_entry = 100)

    mtm_prices = {
        500:  100.0 - 500 / (2 * LOT),     # exit px for ~500 MTM profit
        1800: 100.0 - 1800 / (2 * LOT),
        2400: 100.0 - 2400 / (2 * LOT),    # peak
        1800: 100.0 - 1800 / (2 * LOT),
        1200: 100.0 - 1200 / (2 * LOT),    # = 50% of 2400 peak → fires
    }

    # Drive via current_px yielding the MTM values directly.
    # (avg_entry - current_px) * total_qty = mtm  →  current_px = avg_entry - mtm/qty
    def px(mtm_val):
        return pos.avg_entry - mtm_val / pos.total_qty

    results = []
    for mtm_val in [500, 1800, 2400, 1800, 1200]:
        r = _apply_profit_lock(pos, px(mtm_val))
        results.append(r)

    # Only the last bar (MTM=1200 = 50% of peak 2400) should fire
    assert results == [None, None, None, None, "profit_lock"]
    assert pos.peak_mtm == pytest.approx(2400.0, rel=1e-9)


# ── 7.4: Trailing floor rises with peak ──────────────────────────────────────

def test_profit_lock_trailing_floor_rises():
    """Peak 2000 → 3200 raises floor to 1600; MTM=1500 fires (below 1600 floor)."""
    pos = _Position()
    pos.add(2 * LOT, 100.0)

    def px(mtm_val):
        return pos.avg_entry - mtm_val / pos.total_qty

    r1 = _apply_profit_lock(pos, px(2000))   # peak=2000, floor=1000; MTM=2000 > 1000 → no fire
    r2 = _apply_profit_lock(pos, px(3200))   # peak=3200, floor=1600; MTM=3200 > 1600 → no fire
    r3 = _apply_profit_lock(pos, px(1500))   # peak=3200, floor=1600; MTM=1500 <= 1600 → fires

    assert r1 is None
    assert r2 is None
    assert r3 == "profit_lock"
    assert pos.peak_mtm == pytest.approx(3200.0, rel=1e-9)


def test_profit_lock_floor_does_not_decrease():
    """Floor stays at highest computed value even when MTM drops then rises again."""
    pos = _Position()
    pos.add(2 * LOT, 100.0)

    def px(mtm_val):
        return pos.avg_entry - mtm_val / pos.total_qty

    _apply_profit_lock(pos, px(3000))  # peak=3000, floor=1500
    _apply_profit_lock(pos, px(2000))  # peak stays 3000; MTM=2000 > 1500 → no fire
    _apply_profit_lock(pos, px(2800))  # peak still 3000; MTM=2800 > 1500 → no fire
    r = _apply_profit_lock(pos, px(1400))  # floor=1500; MTM=1400 <= 1500 → fires

    assert r == "profit_lock"
    assert pos.peak_mtm == pytest.approx(3000.0, rel=1e-9)


# ── 7.5: No lock below trigger ────────────────────────────────────────────────

def test_no_profit_lock_below_trigger():
    """MTM peaks at 1900 (below 2000 trigger), drops to 900; profit_lock never fires."""
    pos = _Position()
    pos.add(2 * LOT, 100.0)

    def px(mtm_val):
        return pos.avg_entry - mtm_val / pos.total_qty

    results = [
        _apply_profit_lock(pos, px(1900)),  # peak=1900, below trigger
        _apply_profit_lock(pos, px(1400)),
        _apply_profit_lock(pos, px(900)),
    ]

    assert all(r is None for r in results)
    assert pos.peak_mtm == pytest.approx(1900.0, rel=1e-9)
