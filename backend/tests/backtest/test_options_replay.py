"""Tests for OptionsReplayEngine with mock bar data."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest

from pdp.backtest.options_replay import (
    OptionsReplayEngine,
    _atm,
    _biz_days_in_range,
    _resolve_expiry_synthetic,
    _strike_step,
)
from pdp.backtest.options_strategy import OptionsStrategyConfig

# ---------------------------------------------------------------------------
# Helper to build mock option_bars cursor
# ---------------------------------------------------------------------------

_IST = timedelta(hours=5, minutes=30)


def _to_utc(d: date, t: time) -> datetime:
    ist_dt = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=None)
    return (ist_dt - _IST).replace(tzinfo=UTC)


def _make_bar(d: date, t: time, close: float) -> dict:
    return {"ts": _to_utc(d, t), "close": close}


def _make_option_bar(d: date, t: time, strike: float, opt_type: str, close: float) -> dict:
    return {
        "ts": _to_utc(d, t),
        "close": close,
        "strike": strike,
        "option_type": opt_type,
    }


def _config(**overrides) -> OptionsStrategyConfig:
    base = {
        "type": "options-strategy",
        "name": "Test",
        "underlying": "NIFTY",
        "date_range": {"from": "2026-01-06", "to": "2026-01-06"},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {},
        "lot_size": 75,
        "commissions": False,
    }
    base.update(overrides)
    return OptionsStrategyConfig.model_validate(base)


def _make_engine(spot_docs: list[dict], opt_docs: list[dict]) -> OptionsReplayEngine:
    mongo_db = MagicMock()

    def find_side_effect(query, projection=None):
        coll_name = mongo_db._last_coll
        if coll_name == "market_bars":
            return iter(spot_docs)
        return iter(opt_docs)

    market_col = MagicMock()
    market_col.find.side_effect = lambda q, p=None: iter(spot_docs)

    opt_col = MagicMock()
    opt_col.find.side_effect = lambda q, p=None: iter(opt_docs)
    # No real stored expiries in these mock-data tests — the engine falls back to the
    # synthetic weekday projection, matching `_resolve_expiry_synthetic` below.
    opt_col.distinct.side_effect = lambda field, query=None: []

    mongo_db.__getitem__.side_effect = lambda k: market_col if k == "market_bars" else opt_col
    return OptionsReplayEngine(mongo_db)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_strike_step_nifty():
    assert _strike_step("NIFTY") == 50


def test_strike_step_banknifty():
    assert _strike_step("BANKNIFTY") == 100


def test_atm():
    assert _atm(24073.5, 50) == 24050
    assert _atm(24030.0, 50) == 24050
    assert _atm(24025.0, 50) in (24000, 24050)  # midpoint: either is valid


def test_biz_days():
    days = _biz_days_in_range(date(2026, 1, 5), date(2026, 1, 9))  # Mon–Fri
    assert len(days) == 5
    assert days[0] == date(2026, 1, 5)


def test_resolve_expiry_weekly():
    # 2026-01-06 is a Tuesday — next Tuesday = 2026-01-13
    d = date(2026, 1, 6)
    exp = _resolve_expiry_synthetic(d, "weekly")
    assert exp == date(2026, 1, 13)


# ---------------------------------------------------------------------------
# Replay tests with mock data
# ---------------------------------------------------------------------------

def _run_one_day(
    d: date,
    spot_close: float,
    ce_entry: float,
    pe_entry: float,
    ce_exit: float,
    pe_exit: float,
    risk_override: dict | None = None,
) -> dict:
    entry_t = time(9, 20)
    exit_t = time(15, 10)

    spot_docs = [
        {"ts": _to_utc(d, time(9, 15)), "close": spot_close},
        {"ts": _to_utc(d, time(9, 20)), "close": spot_close},
        {"ts": _to_utc(d, time(9, 25)), "close": spot_close},
        {"ts": _to_utc(d, time(15, 10)), "close": spot_close},
    ]

    atm = _atm(spot_close, 50)
    expiry = _resolve_expiry_synthetic(d, "weekly")
    expiry_dt = datetime(expiry.year, expiry.month, expiry.day, tzinfo=UTC)

    ce_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": ce_entry, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(15, 10)), "close": ce_exit, "strike": atm, "option_type": "CE"},
    ]
    pe_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": pe_entry, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(15, 10)), "close": pe_exit, "strike": atm, "option_type": "PE"},
    ]
    opt_docs = ce_docs + pe_docs

    config_data: dict = {
        "type": "options-strategy",
        "name": "Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": risk_override or {},
        "lot_size": 75,
        "commissions": False,
    }
    config = OptionsStrategyConfig.model_validate(config_data)
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    return {
        "result": result,
        "atm": atm,
    }


def test_basic_entry_exit():
    d = date(2026, 1, 6)
    # CE: sell 100, buy back 80 (+20); PE: sell 80, buy back 60 (+20) → +40 pts * 75 = 3000
    r = _run_one_day(d, 24000.0, ce_entry=100.0, pe_entry=80.0, ce_exit=80.0, pe_exit=60.0)
    result = r["result"]
    assert result.total_trades >= 1
    assert result.total_pnl > 0
    assert len(result.equity_curve) >= 1


def test_combined_sl_triggers_exit():
    d = date(2026, 1, 6)
    spot = 24000.0
    atm = _atm(spot, 50)
    expiry = _resolve_expiry_synthetic(d, "weekly")

    entry_t = time(9, 20)
    sl_t = time(10, 0)
    exit_t = time(15, 10)

    spot_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": spot},
        {"ts": _to_utc(d, time(9, 25)), "close": spot},
        {"ts": _to_utc(d, time(10, 0)), "close": spot},
        {"ts": _to_utc(d, time(15, 10)), "close": spot},
    ]
    # CE entry=100, at 10:00 becomes 130 (+30 loss); PE entry=80, at 10:00 becomes 100 (+20 loss) → -50 pts → SL
    opt_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": 100.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 115.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 130.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 90.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 20)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 90.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 100.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 70.0, "strike": atm, "option_type": "PE"},
    ]
    config = OptionsStrategyConfig.model_validate({
        "type": "options-strategy",
        "name": "SL Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {"combined_sl": {"type": "points", "value": 50}},
        "lot_size": 75,
        "commissions": False,
    })
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    assert result.total_pnl < 0
    assert any(t["exit_reason"] == "combined_sl" for t in result.trade_log)


def test_combined_target_triggers_exit():
    d = date(2026, 1, 6)
    spot = 24000.0
    atm = _atm(spot, 50)

    spot_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": spot},
        {"ts": _to_utc(d, time(9, 25)), "close": spot},
        {"ts": _to_utc(d, time(10, 0)), "close": spot},
        {"ts": _to_utc(d, time(15, 10)), "close": spot},
    ]
    # CE entry=100, drops to 70 (+30 profit); PE entry=80, drops to 80 (0) → +30 pts → target
    opt_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": 100.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 85.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 70.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 60.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 20)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 80.0, "strike": atm, "option_type": "PE"},
    ]
    config = OptionsStrategyConfig.model_validate({
        "type": "options-strategy",
        "name": "Target Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {"combined_target": {"type": "points", "value": 30}},
        "lot_size": 75,
        "commissions": False,
    })
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    assert result.total_pnl > 0
    assert any(t["exit_reason"] == "combined_target" for t in result.trade_log)


def test_trailing_sl_adjusts_and_triggers():
    d = date(2026, 1, 6)
    spot = 24000.0
    atm = _atm(spot, 50)

    spot_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": spot},
        {"ts": _to_utc(d, time(9, 25)), "close": spot},
        {"ts": _to_utc(d, time(9, 30)), "close": spot},
        {"ts": _to_utc(d, time(9, 35)), "close": spot},
        {"ts": _to_utc(d, time(9, 40)), "close": spot},
        {"ts": _to_utc(d, time(15, 10)), "close": spot},
    ]
    # CE entry=100, drops to 70 (pnl=+30), then rises to 80 (pnl=+20)
    # trail_after=20, trail_step=5 → when pnl≥20, trail SL = max_pnl - 5
    # max_pnl reaches 30, trail SL = 25; then pnl drops to 20 → triggers at 25
    opt_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": 100.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 85.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 30)), "close": 70.0, "strike": atm, "option_type": "CE"},  # pnl=+30
        {"ts": _to_utc(d, time(9, 35)), "close": 75.0, "strike": atm, "option_type": "CE"},  # pnl=+25 → triggers at 25
        {"ts": _to_utc(d, time(9, 40)), "close": 75.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 75.0, "strike": atm, "option_type": "CE"},
        # No PE — single leg straddle for simplicity
        {"ts": _to_utc(d, time(9, 20)), "close": 0.01, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 0.01, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 30)), "close": 0.01, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 35)), "close": 0.01, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 40)), "close": 0.01, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 0.01, "strike": atm, "option_type": "PE"},
    ]
    config = OptionsStrategyConfig.model_validate({
        "type": "options-strategy",
        "name": "Trail Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {
            "trailing_sl": {"enabled": True, "trail_after": 20, "trail_step": 5},
        },
        "lot_size": 75,
        "commissions": False,
    })
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    # Should have a trailing_sl exit
    assert any(t["exit_reason"] == "trailing_sl" for t in result.trade_log)


def test_reentry_after_sl():
    d = date(2026, 1, 6)
    spot = 24000.0
    atm = _atm(spot, 50)

    # SL hit at 10:00, then re-entry at 10:00 with new position, exits at 15:10
    spot_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": spot},
        {"ts": _to_utc(d, time(9, 25)), "close": spot},
        {"ts": _to_utc(d, time(10, 0)), "close": spot},
        {"ts": _to_utc(d, time(15, 10)), "close": spot},
    ]
    opt_docs = [
        # First set: CE entry=100, at 10:00 becomes 160 → CE loss = 60, SL triggers
        {"ts": _to_utc(d, time(9, 20)), "close": 100.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 130.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 150.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 90.0, "strike": atm, "option_type": "CE"},
        {"ts": _to_utc(d, time(9, 20)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(9, 25)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(10, 0)), "close": 80.0, "strike": atm, "option_type": "PE"},
        {"ts": _to_utc(d, time(15, 10)), "close": 60.0, "strike": atm, "option_type": "PE"},
    ]
    config = OptionsStrategyConfig.model_validate({
        "type": "options-strategy",
        "name": "Re-entry Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
                {"type": "PE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {
            "combined_sl": {"type": "points", "value": 50},
            "re_entry": {"enabled": True, "max_count": 1},
        },
        "lot_size": 75,
        "commissions": False,
    })
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    # Should have at least 2 trades: initial + re-entry
    assert result.total_trades >= 2
    sl_trades = [t for t in result.trade_log if t["exit_reason"] == "combined_sl"]
    assert len(sl_trades) >= 1


def test_missing_bar_data_skips_day():
    d = date(2026, 1, 6)
    # No option bars for this day — day should be skipped
    spot_docs = [
        {"ts": _to_utc(d, time(9, 20)), "close": 24000.0},
    ]
    opt_docs = []  # no bars

    config = OptionsStrategyConfig.model_validate({
        "type": "options-strategy",
        "name": "Missing Data Test",
        "underlying": "NIFTY",
        "date_range": {"from": d.isoformat(), "to": d.isoformat()},
        "entry": {
            "time_ist": "09:20",
            "legs": [
                {"type": "CE", "side": "SELL", "lots": 1, "strike_selection": {"method": "atm_offset", "offset": 0}},
            ],
        },
        "exit": {"time_ist": "15:10"},
        "risk": {},
        "lot_size": 75,
        "commissions": False,
    })
    engine = _make_engine(spot_docs, opt_docs)
    result = engine.run(config)
    assert result.total_trades == 0
    assert result.total_pnl == 0.0
