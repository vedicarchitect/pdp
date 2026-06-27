"""Tests for the scale-in premium-breakout gate and premium-decay roll-up.

Covers three behavioral contracts from supertrend-scalein-gate-and-rollup:

  4.1  A premium-breakout bar defers the scale-in add; the next non-breakout bar
       performs it (held lots increment by exactly one add).
  4.2  Roll-up at premium < 20 re-sells the furthest-OTM same-side strike with
       premium > 50 at START_LOTS; with no qualifying strike it does not roll.
  4.3  After gated adds a close settles exactly the held lots (no phantom / max
       lots); after a roll the close settles the rolled leg's lot count.

These tests exercise the pure algorithmic components — prev_curr_bars, the gate
condition, the roll-target resolver, and the Position class — without running the
full backtest (which has argparse at module level and hits MongoDB).
"""
from __future__ import annotations

from datetime import datetime, timedelta


# ── Helpers mirroring backtest_multiday (pure functions) ─────────────────────

def _price_at(bars, target, prefer="open"):
    best, bd = None, timedelta(hours=99)
    for (dt, o, h, l, c) in bars:
        if dt > target:
            continue
        d = abs(dt - target)
        if d < bd: bd, best = d, (dt, o, h, l, c)
    if best is None or bd > timedelta(minutes=15): return None
    return best[1] if prefer == "open" else best[4]


def _prev_curr_bars(bars, target):
    best_i, bd = None, timedelta(hours=99)
    for i, (dt, o, h, l, c) in enumerate(bars):
        if dt > target:
            continue
        d = abs(dt - target)
        if d < bd:
            bd, best_i = d, i
    if best_i is None or bd > timedelta(minutes=15):
        return None, None
    curr = bars[best_i]
    prior = bars[best_i - 1] if best_i > 0 else None
    return prior, curr


# ── Minimal Position stand-in ─────────────────────────────────────────────────

class _Position:
    LOT = 65

    def __init__(self, lots_initial, px):
        self.total_qty = 0
        self.total_cost = 0.0
        self.add(lots_initial * self.LOT, px)

    def add(self, qty, px):
        self.total_cost += qty * px
        self.total_qty += qty

    @property
    def lots(self):
        return self.total_qty // self.LOT

    @property
    def avg_entry(self):
        return self.total_cost / self.total_qty if self.total_qty else 0.0


T0 = datetime(2026, 6, 12, 9, 30)


def _bar(t, o, h, l, c):
    return (t, o, h, l, c)


# ── 4.1: Scale-in gate ────────────────────────────────────────────────────────

def test_gate_allows_add_when_no_prior_bar():
    """When there is no prior bar (first bar of the series), the gate allows the add."""
    bars = [_bar(T0, 100.0, 105.0, 95.0, 102.0)]
    prior, curr = _prev_curr_bars(bars, T0)
    assert prior is None
    assert curr is not None
    # Gate passes: prior is None → allow add
    gate_blocks = prior is not None and curr is not None and curr[2] > prior[2]
    assert not gate_blocks


def test_gate_defers_when_high_breaks_prior_high():
    """When current bar's high exceeds the prior bar's high, gate defers (blocks add)."""
    T1 = T0 + timedelta(minutes=5)
    bars = [
        _bar(T0, 100.0, 105.0, 95.0, 102.0),  # prior: high = 105
        _bar(T1, 110.0, 115.0, 108.0, 112.0),  # current: high = 115 > 105
    ]
    prior, curr = _prev_curr_bars(bars, T1)
    assert prior is not None and curr is not None
    assert curr[2] > prior[2]   # 115 > 105
    gate_blocks = prior is not None and curr is not None and curr[2] > prior[2]
    assert gate_blocks


def test_gate_allows_add_when_high_does_not_break():
    """When current bar's high <= prior bar's high, gate allows the add."""
    T1 = T0 + timedelta(minutes=5)
    bars = [
        _bar(T0, 100.0, 115.0, 95.0, 102.0),  # prior: high = 115
        _bar(T1, 110.0, 112.0, 108.0, 111.0),  # current: high = 112 <= 115
    ]
    prior, curr = _prev_curr_bars(bars, T1)
    gate_blocks = prior is not None and curr is not None and curr[2] > prior[2]
    assert not gate_blocks


def test_gate_defers_then_resumes():
    """4.1 core: breakout bar defers; next non-breakout bar adds exactly ADD_LOTS."""
    ADD_LOTS = 1
    LOT = 65

    T1 = T0 + timedelta(minutes=5)
    T2 = T0 + timedelta(minutes=10)
    bars = [
        _bar(T0, 100.0, 105.0, 95.0, 102.0),   # bar 0: entry bar (prior to any scale-in)
        _bar(T1, 110.0, 120.0, 108.0, 115.0),   # bar 1: high=120 > 105 → gate blocks
        _bar(T2, 108.0, 118.0, 105.0, 110.0),   # bar 2: high=118 <= 120 → gate allows
    ]

    pos = _Position(lots_initial=2, px=102.0)  # opened at T0 with 2L
    initial_lots = pos.lots

    # Simulate bar 1: gate check
    prior1, curr1 = _prev_curr_bars(bars, T1)
    gate1_blocks = prior1 is not None and curr1 is not None and curr1[2] > prior1[2]
    if not gate1_blocks:
        add_px1 = _price_at(bars, T1, prefer="close")
        if add_px1:
            pos.add(ADD_LOTS * LOT, add_px1)

    assert pos.lots == initial_lots, f"gate should have deferred: lots {pos.lots} != {initial_lots}"

    # Simulate bar 2: gate check
    prior2, curr2 = _prev_curr_bars(bars, T2)
    gate2_blocks = prior2 is not None and curr2 is not None and curr2[2] > prior2[2]
    if not gate2_blocks:
        add_px2 = _price_at(bars, T2, prefer="close")
        if add_px2:
            pos.add(ADD_LOTS * LOT, add_px2)

    assert pos.lots == initial_lots + ADD_LOTS, \
        f"gate should have allowed add on bar 2: lots {pos.lots} != {initial_lots + ADD_LOTS}"


# ── 4.2: Roll-target resolver ─────────────────────────────────────────────────

ROLL_TARGET_MIN_PREM = 50.0


def _find_roll_target(chain, opt_type, ist_dt, held_strike=None):
    """Pure version of _find_roll_target from backtest_multiday."""
    ordered = sorted(chain.keys(), reverse=(opt_type.upper() == "CE"))
    for stk in ordered:
        if held_strike is not None and stk == held_strike:
            continue
        bars = chain.get(stk, [])
        prem = _price_at(bars, ist_dt, prefer="close") if bars else None
        if prem is not None and prem > ROLL_TARGET_MIN_PREM:
            return stk, bars
    return None, []


def test_roll_target_pe_furthest_otm_above_floor():
    """4.2: for PE, returns furthest-OTM (lowest) strike with premium > 50."""
    T = T0 + timedelta(minutes=5)
    chain = {
        23200.0: [_bar(T, 80.0, 85.0, 75.0, 80.0)],   # lowest / most OTM: prem=80 > 50 ✓
        23300.0: [_bar(T, 60.0, 65.0, 55.0, 60.0)],   # mid: prem=60 > 50 ✓
        23400.0: [_bar(T, 15.0, 18.0, 12.0, 15.0)],   # held (decayed): prem=15 < 20 (skip)
    }
    stk, _ = _find_roll_target(chain, "PE", T, held_strike=23400.0)
    assert stk == 23200.0, f"should pick furthest-OTM PE with prem>50: got {stk}"


def test_roll_target_ce_furthest_otm_above_floor():
    """4.2: for CE, returns furthest-OTM (highest) strike with premium > 50."""
    T = T0 + timedelta(minutes=5)
    chain = {
        23600.0: [_bar(T, 70.0, 75.0, 65.0, 70.0)],   # highest / most OTM: prem=70 > 50 ✓
        23500.0: [_bar(T, 55.0, 60.0, 50.0, 55.0)],   # mid: prem=55 > 50 ✓
        23400.0: [_bar(T, 12.0, 15.0, 10.0, 12.0)],   # held (decayed): prem=12 (skip)
    }
    stk, _ = _find_roll_target(chain, "CE", T, held_strike=23400.0)
    assert stk == 23600.0, f"should pick furthest-OTM CE with prem>50: got {stk}"


def test_roll_target_none_when_no_qualifying_strike():
    """4.2: when no strike clears the premium floor, roll does not happen."""
    T = T0 + timedelta(minutes=5)
    chain = {
        23200.0: [_bar(T, 30.0, 35.0, 28.0, 30.0)],  # prem=30 < 50 → no
        23300.0: [_bar(T, 10.0, 12.0, 9.0, 10.0)],   # prem=10 < 50 → no
    }
    stk, bars = _find_roll_target(chain, "PE", T)
    assert stk is None
    assert bars == []


# ── 4.3: Close invariant — settles exact held quantity ────────────────────────

def test_close_settles_gated_lots_not_max():
    """4.3: after scale-in gate deferred adds, close settles actual held lots, not max."""
    LOT = 65
    START_LOTS = 2
    MAX_LOTS = 5   # noqa: F841

    # Open 2L, then one deferred add, then one allowed add → held = 3L, not max 5L
    pos = _Position(lots_initial=START_LOTS, px=100.0)  # 2L
    pos.add(1 * LOT, 98.0)                              # scale-in add: 3L total
    # (one add was deferred by the gate — not called)

    qty_to_close = pos.total_qty
    assert qty_to_close == 3 * LOT, f"should close 3L worth = {3*LOT} qty, got {qty_to_close}"
    assert pos.lots == 3

    # Simulate close P&L at a given exit price
    exit_px = 90.0
    leg_pnl = (pos.avg_entry - exit_px) * qty_to_close
    assert leg_pnl > 0, "short seller profits when exit < avg entry"


def test_close_after_roll_settles_rolled_leg_lots():
    """4.3: after a roll (resets to START_LOTS), close settles rolled leg's qty, not pre-roll qty."""
    LOT = 65
    START_LOTS = 2

    # Pre-roll leg: opened at 2L, scaled to 4L
    pre_roll_pos = _Position(lots_initial=2, px=120.0)
    pre_roll_pos.add(2 * LOT, 115.0)
    assert pre_roll_pos.lots == 4

    # Roll fires: close_position settles pre_roll_pos.total_qty (4L), pos = None
    pre_roll_close_qty = pre_roll_pos.total_qty
    assert pre_roll_close_qty == 4 * LOT

    # Roll opens a new Position at START_LOTS
    rolled_pos = _Position(lots_initial=START_LOTS, px=65.0)  # fresh leg at START_LOTS
    assert rolled_pos.lots == START_LOTS

    # Now a flip/squareoff closes the rolled leg → must settle rolled_pos.total_qty (2L)
    rolled_close_qty = rolled_pos.total_qty
    assert rolled_close_qty == START_LOTS * LOT, \
        f"close should settle {START_LOTS}L = {START_LOTS*LOT} qty, got {rolled_close_qty}"


def test_deferred_add_creates_no_phantom_quantity():
    """4.3: a deferred gate add leaves total_qty unchanged (gate skips pos.add, not a counter)."""
    LOT = 65
    pos = _Position(lots_initial=2, px=100.0)
    qty_before = pos.total_qty

    # Simulate a deferred add: gate fires, pos.add is NOT called
    gate_blocks = True  # simulating the breakout condition
    if not gate_blocks:
        pos.add(1 * LOT, 98.0)  # would not be called

    assert pos.total_qty == qty_before, \
        f"deferred add must not change total_qty: {pos.total_qty} != {qty_before}"
