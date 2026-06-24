"""Smoke test for the multi-timeframe strangle loader.

Builds a synthetic ``WindowData`` (no Mongo) with enough prior trading days to seed the 1h EMA(50),
then asserts ``build_strangle_day`` assembles decision bars whose ``BiasInputs`` carry populated
multi-timeframe EMAs, Camarilla levels, swing levels, VWAP and the opening range.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pdp.backtest.day_loader import WindowData
from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_loader import build_strangle_day

_IST = timedelta(hours=5, minutes=30)


def _day_bars(d: date, base: float) -> list[dict]:
    """A full 09:15-15:29 IST session of 1m bars with a gentle intraday drift."""
    bars = []
    start = datetime(d.year, d.month, d.day, 9, 15) - _IST  # store ts in UTC
    for i in range(375):
        px = base + i * 0.05
        ts = (start + timedelta(minutes=i)).replace(tzinfo=UTC)
        bars.append({"ts": ts, "open": px, "high": px + 1, "low": px - 1,
                     "close": px, "volume": 1000})
    return bars


def _weekdays_before(end: date, n: int) -> list[date]:
    days, d = [], end - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def _window(trade_date: date) -> WindowData:
    prior = _weekdays_before(trade_date, 25)
    spot: dict[date, list[dict]] = {}
    base = 19_000.0
    for i, d in enumerate(prior):
        spot[d] = _day_bars(d, base + i * 30.0)  # rising base => bullish EMA stack
    spot[trade_date] = _day_bars(trade_date, base + len(prior) * 30.0)
    return WindowData(
        spot_1m_by_day=spot,
        chain_1m={},
        expiry_by_day={trade_date: trade_date},
        valid_days=[trade_date],
    )


def test_loader_assembles_multitimeframe_bias():
    td = date(2026, 6, 2)  # a Tuesday
    data = build_strangle_day(_window(td), StrangleConfig(), td)
    assert data is not None
    assert data.decision_bars
    # Late-session bar: all timeframe EMAs should have seeded (incl. 1h EMA50).
    last = data.decision_bars[-1]
    b = last.bias
    assert b.ema_1h is not None, "1h EMA failed to seed — warmup window too short"
    assert b.ema_15m is not None
    assert b.ema_5m is not None
    # Rising series -> 1h EMAs stacked bullish (9 > 20 > 50).
    assert b.ema_1h.ema9 > b.ema_1h.ema20 > b.ema_1h.ema50
    # Day-level levels populated from prior period.
    assert b.cam_daily is not None and b.cam_daily.r3 > b.cam_daily.s3
    assert b.pdh is not None and b.pdl is not None
    assert b.pwh is not None and b.pwl is not None
    assert b.orb_high is not None and b.orb_low is not None
    assert b.vwap is not None


def test_loader_returns_none_without_spot():
    td = date(2026, 6, 2)
    empty = WindowData(spot_1m_by_day={}, chain_1m={}, expiry_by_day={td: td}, valid_days=[td])
    assert build_strangle_day(empty, StrangleConfig(), td) is None
