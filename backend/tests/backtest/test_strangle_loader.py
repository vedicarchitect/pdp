"""Smoke test for the multi-timeframe strangle loader.

Builds a synthetic ``WindowData`` (no Mongo) with enough prior trading days to seed the 1h EMA(50),
multi-timeframe EMAs, Camarilla levels, swing levels, and the opening range.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pdp.backtest.day_loader import WindowData
from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_loader import _option_series_reads, build_strangle_day
from pdp.indicators.ema import EMATracker
from pdp.indicators.psar import ParabolicSARTracker
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.signals.bias import BiasWeights, tf_ema_from_values

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


def _opt_day_bars(d: date, strike: float, base: float) -> list[tuple]:
    """A session of IST-naive ``(dt, o, h, lo, c)`` 1m option bars for one strike."""
    bars = []
    start = datetime(d.year, d.month, d.day, 9, 15)  # IST-naive (chain_1m frame)
    for i in range(375):
        px = base + i * 0.02
        dt = start + timedelta(minutes=i)
        bars.append((dt, px, px + 0.5, px - 0.5, px))
    return bars


def _window(trade_date: date, with_chain: bool = False) -> WindowData:
    prior = _weekdays_before(trade_date, 25)
    spot: dict[date, list[dict]] = {}
    base = 19_000.0
    for i, d in enumerate(prior):
        spot[d] = _day_bars(d, base + i * 30.0)  # rising base => bullish EMA stack
    spot[trade_date] = _day_bars(trade_date, base + len(prior) * 30.0)
    chain: dict = {}
    if with_chain:
        # Spot on the trade day runs ~19750 -> ~19768, so cover the ATM 50-grid around it.
        for opt in ("CE", "PE"):
            chain[(trade_date, opt)] = {
                float(stk): _opt_day_bars(trade_date, float(stk), 120.0)
                for stk in (19_700, 19_750, 19_800, 19_850)
            }
    return WindowData(
        spot_1m_by_day=spot,
        chain_1m=chain,
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


def test_loader_returns_none_without_spot():
    td = date(2026, 6, 2)
    empty = WindowData(spot_1m_by_day={}, chain_1m={}, expiry_by_day={td: td}, valid_days=[td])
    assert build_strangle_day(empty, StrangleConfig(), td) is None


def test_loader_populates_supertrend_and_psar_votes():
    """New st_*/psar_* BiasInputs fields warm from the prefix and are set on late bars."""
    td = date(2026, 6, 2)
    data = build_strangle_day(_window(td), StrangleConfig(), td)
    assert data is not None
    b = data.decision_bars[-1].bias
    # Warmed with a 20-day prefix, all three timeframes' SuperTrend + PSAR have seeded.
    assert b.st_1h is not None and b.st_15m is not None and b.st_5m is not None
    assert b.psar_1h is not None and b.psar_15m is not None and b.psar_5m is not None
    # Rising series -> both SuperTrend variants and the SAR point up (+1) on the higher TFs.
    assert b.st_1h == (1, 1)
    assert b.psar_1h == 1


def test_loader_atm_read_off_by_default_on_by_weight():
    """ATM CE/PE reads stay None when w_atm==0 (inert) and populate as SeriesInputs when weighted."""
    td = date(2026, 6, 2)

    # Default weights (w_atm == 0.0): ATM reads are not built even if a chain is present.
    default_cfg = StrangleConfig()
    data_off = build_strangle_day(_window(td, with_chain=True), default_cfg, td)
    assert data_off is not None
    assert all(bar.bias.atm_ce_5m is None and bar.bias.atm_pe_5m is None
               for bar in data_off.decision_bars)

    # Weighted ATM vote: reads resolve at the ATM strike and carry EMA/ST/PSAR sub-reads.
    weighted = BiasWeights(w_atm=1.0)
    cfg = StrangleConfig(weights=weighted)
    data_on = build_strangle_day(_window(td, with_chain=True), cfg, td)
    assert data_on is not None
    late = data_on.decision_bars[-1].bias
    assert late.atm_ce_5m is not None and late.atm_pe_5m is not None
    # By late session the option EMA(50) and SuperTrend have seeded on the ATM strike.
    assert late.atm_ce_5m.st is not None
    assert late.atm_ce_5m.psar is not None


def test_option_series_reads_parity_with_live_tracker_sequence():
    """Parity (6.3): the loader's ATM option trend read matches an independent replay through
    the exact tracker classes/params the live `atm_suite.atm_trend_read` uses — so the same
    option bars produce an identical `SeriesInputs` on both the backtest and live paths."""
    td = date(2026, 6, 2)
    bars = _opt_day_bars(td, 19_750.0, 120.0)
    cfg = StrangleConfig()  # st_fast=(10,2), st_slow=(10,3), psar defaults — same as live

    _times, reads = _option_series_reads(bars, cfg)
    loader_last = reads[-1]

    # Independent replay mirroring atm_suite.atm_trend_read's tracker sequence.
    tr_ema = EMATracker(periods=[9, 20, 50])
    st_fast = SuperTrendTracker(10, 2.0)
    st_slow = SuperTrendTracker(10, 3.0)
    psar = ParabolicSARTracker()
    es = sf = ss = ps = None
    last_close = 0.0
    for (dt, _o, h, lo, c) in bars:
        es = tr_ema.update(h, lo, c, 0.0, dt)
        sf = st_fast.update(h, lo, c, dt)
        ss = st_slow.update(h, lo, c, dt)
        ps = psar.update(h, lo, c, 0.0, dt)
        last_close = c
    live_ema = tf_ema_from_values(dict(es.values) if es is not None else None, last_close)
    live_st = (sf.direction, ss.direction) if (sf is not None and ss is not None) else None
    live_psar = ps.direction if ps is not None else None

    assert loader_last.st == live_st
    assert loader_last.psar == live_psar
    assert (loader_last.ema is None) == (live_ema is None)
    if loader_last.ema is not None and live_ema is not None:
        assert loader_last.ema.ema50 == live_ema.ema50
        assert loader_last.ema.ema9 == live_ema.ema9
