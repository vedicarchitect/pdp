"""Tests for the configurable strategy engine (``pdp.backtest.sim``) and sweep aggregation.

Covers the new semantics introduced by ``configurable-strategy-backtest-sweep``:

  * ``select_strike`` signed-moneyness mapping for CE and PE (ITM/ATM/OTM).
  * The option-premium scale-in gate (``_scale_gate_open``) across all modes.
  * ``StrategyConfig`` round-trip + validation.
  * The flip -> strangle -> flip-candle-break state machine end to end in ``simulate_day``.
  * Sweep metric aggregation (profit factor, win rate, drawdown).

All tests are pure (no DB): ``simulate_day`` consumes a hand-built ``DayData``.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, time, timedelta

import pytest

from pdp.backtest.sim import (
    DayData,
    _scale_gate_open,
    select_strike,
    simulate_day,
)
from pdp.backtest.strategy_config import (
    FLIP_CLOSE_ALL,
    FLIP_STRANGLE,
    SCALE_ALWAYS,
    SCALE_PREMIUM_BREAK,
    SCALE_PREMIUM_NO_NEW_HIGH,
    StrategyConfig,
)

_IST = timedelta(hours=5, minutes=30)


# ── select_strike: signed moneyness ──────────────────────────────────────────
@pytest.mark.parametrize(
    "spot, opt, mny, expected",
    [
        (20013, "CE", 0, 20000),   # ATM
        (20013, "CE", 1, 20050),   # OTM-1 (higher)
        (20013, "CE", 2, 20100),   # OTM-2
        (20013, "CE", -1, 19950),  # ITM-1 (lower)
        (20013, "PE", 0, 20000),   # ATM
        (20013, "PE", 1, 19950),   # OTM-1 (lower)
        (20013, "PE", 2, 19900),   # OTM-2
        (20013, "PE", -1, 20050),  # ITM-1 (higher)
    ],
)
def test_select_strike_signed_moneyness(spot, opt, mny, expected):
    assert select_strike(spot, opt, mny, 50) == expected


def test_select_strike_rounds_to_nearest_atm():
    # 20024 rounds down to 20000; 20026 rounds up to 20050.
    assert select_strike(20024, "CE", 0, 50) == 20000
    assert select_strike(20026, "CE", 0, 50) == 20050


# ── scale-in gate ────────────────────────────────────────────────────────────
def _bar(t, o, h, lo, c):
    return (t, o, h, lo, c)


def test_scale_gate_premium_break_adds_on_low_break():
    """premium_break: add only when current low < prior low (decay continuing)."""
    cfg = StrategyConfig(scale_in_gate=SCALE_PREMIUM_BREAK)
    t0 = datetime(2026, 6, 12, 9, 30)
    t1 = t0 + timedelta(minutes=5)
    bars = [_bar(t0, 100, 105, 95, 98), _bar(t1, 98, 100, 90, 92)]  # low 90 < 95
    assert _scale_gate_open(cfg, bars, t1) is True


def test_scale_gate_premium_break_blocks_without_low_break():
    cfg = StrategyConfig(scale_in_gate=SCALE_PREMIUM_BREAK)
    t0 = datetime(2026, 6, 12, 9, 30)
    t1 = t0 + timedelta(minutes=5)
    bars = [_bar(t0, 100, 105, 95, 98), _bar(t1, 98, 100, 96, 97)]  # low 96 >= 95
    assert _scale_gate_open(cfg, bars, t1) is False


def test_scale_gate_no_new_high_blocks_on_new_high():
    """premium_no_new_high (legacy): block when current high > prior high."""
    cfg = StrategyConfig(scale_in_gate=SCALE_PREMIUM_NO_NEW_HIGH)
    t0 = datetime(2026, 6, 12, 9, 30)
    t1 = t0 + timedelta(minutes=5)
    bars = [_bar(t0, 100, 105, 95, 98), _bar(t1, 106, 110, 104, 108)]  # high 110 > 105
    assert _scale_gate_open(cfg, bars, t1) is False
    bars2 = [_bar(t0, 100, 105, 95, 98), _bar(t1, 100, 103, 96, 99)]  # high 103 <= 105
    assert _scale_gate_open(cfg, bars2, t1) is True


def test_scale_gate_always():
    cfg = StrategyConfig(scale_in_gate=SCALE_ALWAYS)
    t0 = datetime(2026, 6, 12, 9, 30)
    bars = [_bar(t0, 100, 105, 95, 98)]
    assert _scale_gate_open(cfg, bars, t0) is True


def test_scale_gate_no_prior_bar_blocks_break_mode():
    """With no prior bar, premium_break cannot confirm a break -> no add."""
    cfg = StrategyConfig(scale_in_gate=SCALE_PREMIUM_BREAK)
    t0 = datetime(2026, 6, 12, 9, 30)
    bars = [_bar(t0, 100, 105, 95, 98)]
    assert _scale_gate_open(cfg, bars, t0) is False


# ── StrategyConfig round-trip + validation ───────────────────────────────────
def test_config_roundtrip():
    cfg = StrategyConfig(st_period=10, st_multiplier=2, timeframe_min=15, moneyness=-1)
    again = StrategyConfig.from_dict(cfg.to_dict())
    assert again.to_dict() == cfg.to_dict()


def test_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown"):
        StrategyConfig.from_dict({"st_period": 10, "bogus": 1})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"st_period": 0},
        {"st_multiplier": 0},
        {"timeframe_min": 7},
        {"base_lots": 0},
        {"max_lots": 1, "base_lots": 2},
        {"scale_in_gate": "nope"},
        {"flip_mode": "nope"},
    ],
)
def test_config_validation_raises(kwargs):
    with pytest.raises(ValueError):
        StrategyConfig(**kwargs)


def test_config_label():
    assert StrategyConfig(st_period=10, st_multiplier=2, timeframe_min=15, moneyness=0).label() == "ST(10,2) 15m ATM"
    assert StrategyConfig(st_period=3, st_multiplier=1, timeframe_min=5, moneyness=-2).label() == "ST(3,1) 5m ITM2"


# ── DayData builders for the state-machine tests ─────────────────────────────
def _utc(td: date, hh: int, mm: int) -> datetime:
    """IST wall-clock -> UTC tz-aware ts (engine converts back to IST internally)."""
    ist = datetime(td.year, td.month, td.day, hh, mm)
    return (ist - _IST).replace(tzinfo=UTC)


def _spot_bar(td, hh, mm, o, h, lo, c):
    return {"ts": _utc(td, hh, mm), "open": o, "high": h, "low": lo, "close": c}


def _opt_bar(td, hh, mm, o, h, lo, c):
    return (datetime(td.year, td.month, td.day, hh, mm), o, h, lo, c)


def _flat_chain(td, strikes_ce, strikes_pe, times, premium=100.0):
    """Build a day chain with a constant premium across the given strikes & times."""
    chain = {"CE": {}, "PE": {}}
    for stk in strikes_ce:
        chain["CE"][float(stk)] = [_opt_bar(td, h, m, premium, premium, premium, premium) for (h, m) in times]
    for stk in strikes_pe:
        chain["PE"][float(stk)] = [_opt_bar(td, h, m, premium, premium, premium, premium) for (h, m) in times]
    return chain


# ── flip -> strangle -> flip-candle-break state machine ──────────────────────
def test_flip_strangle_resolves_on_high_break_closes_ce():
    """FLIP_STRANGLE: after a flip arming a strangle, a NIFTY high break closes the short CE."""
    td = date(2026, 6, 12)
    cfg = StrategyConfig(
        st_period=2, st_multiplier=1, timeframe_min=5, moneyness=1,
        base_lots=1, add_lots=1, max_lots=2, roll_enabled=False,
        scale_in_gate=SCALE_ALWAYS, flip_mode=FLIP_STRANGLE,
        start_ist=time(9, 30), squareoff_ist=time(15, 10),
    )
    # Build a rising-then-falling-then-rising spot so ST flips at least twice.
    times = [(9, h // 60 % 60) for h in range(0)]  # placeholder
    # Construct 5-min bars from 09:15 to 14:00.
    minutes = [(9, 15), (9, 20), (9, 25), (9, 30), (9, 35), (9, 40), (9, 45), (9, 50),
               (9, 55), (10, 0), (10, 5), (10, 10), (10, 15), (10, 20)]
    # Price path: strong uptrend (ST turns green -> short PE), then sharp drop (flip -> short CE,
    # keep PE as strangle), then a high break above the flip candle's high (closes the CE).
    closes = [100, 110, 125, 140, 160, 185, 215, 250,  # up: ST green
              230, 205, 175,                            # down: ST flips red (flip candle here)
              260, 300, 340]                            # sharp rise: breaks flip-candle high
    spot = []
    base = 20000
    for (hh, mm), c in zip(minutes, closes):
        px = base + c
        spot.append(_spot_bar(td, hh, mm, px - 2, px + 30, px - 30, px))
    all_times = minutes
    # Wide chain so both legs and their strikes resolve at any spot.
    strikes = [base + 100 + 50 * k for k in range(-40, 60)]
    chain = _flat_chain(td, strikes, strikes, all_times, premium=80.0)
    data = DayData(trade_date=td, expiry_date=td, nifty_bars=spot, prior_session_bars=[], day_chain=chain)

    res = simulate_day(cfg, data)
    assert res is not None
    notes = [t.note for t in res.trades]
    # A flip should have opened the opposite base (flip_open) and a high break should resolve it.
    assert any("flip_open" in n for n in notes), notes
    assert any(t.note == "strangle_break_up" for t in res.trades), notes


def test_flip_close_all_mode_reopens_opposite():
    """FLIP_CLOSE_ALL: on flip everything closes and the opposite base reopens (no strangle)."""
    td = date(2026, 6, 12)
    cfg = StrategyConfig(
        st_period=2, st_multiplier=1, timeframe_min=5, moneyness=1,
        base_lots=1, add_lots=1, max_lots=2, roll_enabled=False,
        scale_in_gate=SCALE_ALWAYS, flip_mode=FLIP_CLOSE_ALL,
        start_ist=time(9, 30), squareoff_ist=time(15, 10),
    )
    minutes = [(9, 15), (9, 20), (9, 25), (9, 30), (9, 35), (9, 40), (9, 45), (9, 50),
               (9, 55), (10, 0), (10, 5), (10, 10)]
    closes = [100, 120, 145, 175, 210, 250, 295,  # up
              260, 220, 175, 130, 90]             # down -> flip
    base = 20000
    spot = [_spot_bar(td, hh, mm, base + c - 2, base + c + 25, base + c - 25, base + c)
            for (hh, mm), c in zip(minutes, closes)]
    strikes = [base + 50 * k for k in range(-40, 60)]
    chain = _flat_chain(td, strikes, strikes, minutes, premium=80.0)
    data = DayData(trade_date=td, expiry_date=td, nifty_bars=spot, prior_session_bars=[], day_chain=chain)

    res = simulate_day(cfg, data)
    assert res is not None
    notes = [t.note for t in res.trades]
    assert any(n == "flip" for n in notes), notes
    # close_all mode must never produce strangle-resolution exits.
    assert not any("strangle" in n for n in notes), notes


def test_squareoff_flattens_all_legs():
    td = date(2026, 6, 12)
    cfg = StrategyConfig(
        st_period=2, st_multiplier=1, timeframe_min=5, moneyness=1,
        base_lots=1, roll_enabled=False, scale_in_gate=SCALE_ALWAYS,
        start_ist=time(9, 30), squareoff_ist=time(10, 0),
    )
    minutes = [(9, 15), (9, 20), (9, 25), (9, 30), (9, 35), (9, 40), (9, 45), (9, 50), (9, 55), (10, 0), (10, 5)]
    closes = [100, 120, 145, 175, 210, 250, 295, 340, 390, 440, 490]
    base = 20000
    spot = [_spot_bar(td, hh, mm, base + c - 2, base + c + 25, base + c - 25, base + c)
            for (hh, mm), c in zip(minutes, closes)]
    strikes = [base + 50 * k for k in range(-40, 60)]
    chain = _flat_chain(td, strikes, strikes, minutes, premium=80.0)
    data = DayData(trade_date=td, expiry_date=td, nifty_bars=spot, prior_session_bars=[], day_chain=chain)

    res = simulate_day(cfg, data)
    assert res is not None
    # A squareoff exit must appear and no leg should remain open (BUY qty == SELL qty).
    sell_qty = sum(t.qty for t in res.trades if t.side == "SELL")
    buy_qty = sum(t.qty for t in res.trades if t.side == "BUY")
    assert sell_qty == buy_qty, [(t.side, t.qty, t.note) for t in res.trades]
    assert any("squareoff" in t.note for t in res.trades)


def test_partial_close_preserves_avg_entry_books_real_loss():
    """Regression: a partial close (flip-trim) must NOT inflate the surviving leg's avg entry.

    Build a falling spot so ST flips green->red, opening a short PE that then gets trimmed on
    the flip while its premium rises (adverse). The trimmed PE must book a genuine LOSS, not a
    phantom profit from an inflated average entry.
    """
    td = date(2026, 6, 12)
    cfg = StrategyConfig(
        st_period=2, st_multiplier=1, timeframe_min=5, moneyness=1,
        base_lots=2, add_lots=1, max_lots=4, roll_enabled=False,
        scale_in_gate=SCALE_ALWAYS, flip_mode=FLIP_STRANGLE,
        start_ist=time(9, 30), squareoff_ist=time(15, 10),
    )
    minutes = [(9, 15), (9, 20), (9, 25), (9, 30), (9, 35), (9, 40), (9, 45),
               (9, 50), (9, 55), (10, 0), (10, 5), (10, 10), (10, 15)]
    # Rise (ST green -> short PE), scale, then fall (flip -> trim PE) and keep falling (PE adverse).
    closes = [100, 140, 190, 250, 320, 400,  # up: short PE accumulates
              360, 300, 230, 150, 80, 20]    # down: flip, PE premium rises = loss
    base = 20000
    spot = [_spot_bar(td, hh, mm, base + c - 2, base + c + 30, base + c - 30, base + c)
            for (hh, mm), c in zip(minutes, closes + [closes[-1]])][:len(minutes)]
    strikes = [base + 50 * k for k in range(-60, 60)]
    # PE premium RISES through the day (adverse for a short PE); CE falls.
    chain = {"CE": {}, "PE": {}}
    rising = {(h, m): 60 + i * 12 for i, (h, m) in enumerate(minutes)}
    for stk in strikes:
        chain["PE"][float(stk)] = [_opt_bar(td, h, m, rising[(h, m)], rising[(h, m)] + 5,
                                            rising[(h, m)] - 5, rising[(h, m)]) for (h, m) in minutes]
        chain["CE"][float(stk)] = [_opt_bar(td, h, m, 80, 82, 78, 80) for (h, m) in minutes]
    data = DayData(trade_date=td, expiry_date=td, nifty_bars=spot, prior_session_bars=[], day_chain=chain)
    res = simulate_day(cfg, data)
    assert res is not None
    pe_exits = [t for t in res.trades if t.side == "BUY" and t.opt_type == "PE" and t.leg_pnl is not None]
    assert pe_exits, [(t.side, t.opt_type, t.note) for t in res.trades]
    # Every short-PE exit while premium was rising must be a loss (no inflated-avg phantom profit).
    assert all(t.leg_pnl < 0 for t in pe_exits), [(t.note, t.leg_pnl) for t in pe_exits]


# ── sweep aggregation ────────────────────────────────────────────────────────
def _load_aggregate():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "scripts"))
    from backtest_sweep import aggregate
    return aggregate


class _R:
    def __init__(self, realized, trades=1, done_reason=""):
        self.realized = realized
        self.trades = list(range(trades))
        self.done_reason = done_reason


def test_aggregate_profit_factor_and_winrate():
    aggregate = _load_aggregate()
    m = aggregate([_R(100), _R(-50), _R(200), _R(-25)])
    assert m["gross_profit"] == 300
    assert m["gross_loss"] == -75
    assert m["net"] == 225
    assert m["profit_factor"] == pytest.approx(4.0)
    assert m["win_rate"] == pytest.approx(50.0)
    assert m["days"] == 4


def test_aggregate_drawdown():
    aggregate = _load_aggregate()
    # equity: +100, +50, +250, +50 -> peak 250 then 50 = DD 200
    m = aggregate([_R(100), _R(-50), _R(200), _R(-200)])
    assert m["max_dd"] == pytest.approx(200.0)


def test_aggregate_infinite_pf_when_no_losses():
    aggregate = _load_aggregate()
    m = aggregate([_R(100), _R(50)])
    assert m["profit_factor"] == float("inf")
