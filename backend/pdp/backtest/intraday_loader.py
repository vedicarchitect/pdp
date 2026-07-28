"""Assemble per-bar ``IntradayInputs`` for the intraday-directional backtest.

The bridge between the cached Mongo window (``day_loader.WindowData``) and the pure
``intraday_sim`` engine. For one trade day it:

  * resamples 1m spot to the decision timeframe (e.g. 5m) and to the confirmation
    timeframe (15m),
  * replays ``EMATracker`` and ``SuperTrendTracker`` per timeframe, warmed with a
    multi-day prior window, so the indicator state matches the live engine's,
  * computes the session VWAP proxy from the 1m series,
  * captures the opening range strictly from the 15m bar stamped ``orb_start_ist``,
  * computes daily Camarilla levels from the prior session's high/low/close,

and emits an ``IntradayDayData`` whose ``decision_bars`` each carry a fully-populated
``IntradayInputs`` — everything except ``option_st_dir``, which depends on which strike
is actually held and is therefore resolved by the engine through ``OptionTrendReader``.

Timestamp convention matches ``strangle_loader``: a resampled bar is stamped at its
bucket **start** in naive IST, and a decision taken "at" that stamp uses that bucket's
close, priced from the option bar carrying the same stamp. Both engines therefore fill
on the same bar they signal on, which is what makes their P&L comparable.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from pdp.backtest.day_loader import WindowData, _prior_session_1m, _resample_spot_ist
from pdp.backtest.intraday_config import VWAP_OFF, IntradayDirectionalConfig
from pdp.backtest.resample import resample_ohlcv
from pdp.indicators.ema import EMATracker
from pdp.indicators.pivots import camarilla_levels
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.signals.bias import CamLevels
from pdp.signals.intraday_directional import IntradayInputs

__all__ = [
    "IntradayDayData",
    "IntradayDecisionBar",
    "OptionTrendReader",
    "build_intraday_day",
]

_IST = timedelta(hours=5, minutes=30)

# EMA(20) on the confirmation timeframe needs a multi-day prefix to converge; the same
# window warms the SuperTrend ATR. Matches ``strangle_loader._EMA_WARMUP_DAYS``.
_WARMUP_DAYS = 20


def _asof(times: list[datetime], target: datetime) -> int | None:
    """Index of the latest entry at or before ``target`` (no look-ahead), else None."""
    i = bisect_right(times, target) - 1
    return i if i >= 0 else None


def _at(times: list[datetime], vals: list, target: datetime):
    i = _asof(times, target)
    return vals[i] if i is not None else None


def _ist_of(bar: dict) -> datetime:
    ts = bar["ts"] if bar["ts"].tzinfo else bar["ts"].replace(tzinfo=UTC)
    return (ts + _IST).replace(tzinfo=None)


def _hlc(bars: list[dict]) -> tuple[float, float, float] | None:
    """(high, low, close) over a set of 1m docs."""
    if not bars:
        return None
    return (
        max(float(b["high"]) for b in bars),
        min(float(b["low"]) for b in bars),
        float(bars[-1]["close"]),
    )


def _prior_days_1m(window: WindowData, trade_date: date, n_days: int) -> list[dict]:
    """Concatenated 1m spot for up to ``n_days`` trading days before ``trade_date``."""
    out: list[dict] = []
    picked = 0
    for d in sorted((x for x in window.spot_1m_by_day if x < trade_date), reverse=True):
        out.extend(window.spot_1m_by_day[d])
        picked += 1
        if picked >= n_days:
            break
    out.sort(key=lambda b: b["ts"])
    return out


def _daily_camarilla(prior_bars: list[dict]) -> CamLevels | None:
    """Camarilla band from the prior session's HLC, via the canonical pivot math."""
    hlc = _hlc(prior_bars)
    if hlc is None:
        return None
    r3, r4, s3, s4 = camarilla_levels(*hlc)
    return CamLevels(r3=r3, r4=r4, s3=s3, s4=s4)


# --------------------------------------------------------------------------- #
# Indicator series
# --------------------------------------------------------------------------- #


def _ema_series(
    bars: list[dict], prior_bars: list[dict], fast: int, slow: int
) -> tuple[list[datetime], list[float | None], list[float | None]]:
    """(times, ema_fast, ema_slow) per bar, warmed with ``prior_bars``.

    An unconverged period yields ``None`` rather than a partial value, so the core's
    fail-closed rule sees a genuine absence.
    """
    tr = EMATracker(periods=[fast, slow])
    for wb in prior_bars:
        ts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
        tr.update(wb["high"], wb["low"], wb["close"], 0.0, ts)
    times: list[datetime] = []
    fast_vals: list[float | None] = []
    slow_vals: list[float | None] = []
    for b in bars:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        st = tr.update(b["high"], b["low"], b["close"], 0.0, ts)
        times.append(_ist_of(b))
        vals = dict(st.values) if st is not None else {}
        fast_vals.append(vals.get(fast))
        slow_vals.append(vals.get(slow))
    return times, fast_vals, slow_vals


def _st_series(
    bars: list[dict], prior_bars: list[dict], period: int, mult: float
) -> tuple[list[datetime], list[int | None]]:
    """(times, supertrend_direction) per bar, warmed with ``prior_bars``."""
    tr = SuperTrendTracker(period, mult)
    for wb in prior_bars:
        ts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
        tr.update(wb["high"], wb["low"], wb["close"], ts)
    times: list[datetime] = []
    dirs: list[int | None] = []
    for b in bars:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        st = tr.update(b["high"], b["low"], b["close"], ts)
        times.append(_ist_of(b))
        dirs.append(st.direction if st is not None else None)
    return times, dirs


def _session_vwap_series(
    bars_1m: list[dict], source: str
) -> tuple[list[datetime], list[float | None]]:
    """Session-anchored VWAP proxy per 1m bar.

    The spot index carries no traded volume, so a true volume-weighted average can
    never converge on it. ``session_twap`` accumulates the unweighted mean of typical
    price ``(h+l+c)/3`` from the session open — the same accumulation the live path
    performs on 1m bar closes, so both produce identical values.
    """
    times: list[datetime] = []
    vals: list[float | None] = []
    if source == VWAP_OFF:
        return times, vals
    total = 0.0
    count = 0
    for b in bars_1m:
        typical = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        total += typical
        count += 1
        times.append(_ist_of(b))
        vals.append(total / count)
    return times, vals


# --------------------------------------------------------------------------- #
# Option-chart SuperTrend
# --------------------------------------------------------------------------- #


class OptionTrendReader:
    """SuperTrend direction on an option strike's own decision-timeframe chart.

    Memoised per ``(option_type, strike)``: a strike held across many bars is replayed
    once. There is no warmup prefix — an option contract's bars only exist for the trade
    day — so the direction is ``None`` until the tracker seeds, and the core treats that
    as an abstention rather than an exit signal. Mirrors the live
    ``atm_suite.option_trend_read`` path, which replays the same tracker class over the
    same rolled-up bars.
    """

    __slots__ = ("_cache", "_chain", "_mult", "_period")

    def __init__(
        self, day_chain: dict[str, dict[float, list]], period: int, mult: float
    ) -> None:
        self._chain = day_chain
        self._period = period
        self._mult = mult
        self._cache: dict[tuple[str, float], tuple[list[datetime], list[int | None]]] = {}

    def _series(self, opt_type: str, strike: float) -> tuple[list[datetime], list[int | None]]:
        key = (opt_type.upper(), float(strike))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        bars = self._chain.get(key[0], {}).get(key[1], [])
        tr = SuperTrendTracker(self._period, self._mult)
        times: list[datetime] = []
        dirs: list[int | None] = []
        for row in bars:
            dt, _o, high, low, close = row[0], row[1], row[2], row[3], row[4]
            st = tr.update(high, low, close, dt)
            times.append(dt)
            dirs.append(st.direction if st is not None else None)
        self._cache[key] = (times, dirs)
        return times, dirs

    def direction_at(
        self, opt_type: str, strike: float, ist_dt: datetime
    ) -> int | None:
        times, dirs = self._series(opt_type, strike)
        if not times:
            return None
        return _at(times, dirs, ist_dt)


# --------------------------------------------------------------------------- #
# Day data
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class IntradayDecisionBar:
    """One decision-timeframe bar plus the fully-assembled inputs at its close."""

    ist_dt: datetime
    open: float
    high: float
    low: float
    close: float
    inputs: IntradayInputs


@dataclass(slots=True)
class IntradayDayData:
    """Everything ``simulate_intraday_day`` needs for one trade day."""

    trade_date: date
    expiry_date: date
    decision_bars: list[IntradayDecisionBar]
    day_chain: dict[str, dict[float, list]]
    option_trend: OptionTrendReader
    spot_open: float
    spot_close: float
    orb_high: float | None
    orb_low: float | None


def _find_orb_bar(bars_15: list[dict], orb_start: time) -> dict | None:
    """The confirmation-timeframe bar stamped exactly at ``orb_start`` (09:15 IST).

    Deliberately stricter than picking ``bars_15[0]``: a session whose first bar is not
    the opening-range candle (late data, a truncated session) must leave the range
    un-seeded so the engine blocks the day, rather than silently using the wrong window.
    """
    for b in bars_15:
        if _ist_of(b).time() == orb_start:
            return b
    return None


def build_intraday_day(
    window: WindowData,
    cfg: IntradayDirectionalConfig,
    trade_date: date,
) -> IntradayDayData | None:
    """Assemble one trade day of decision bars with fully-populated ``IntradayInputs``."""
    raw1 = window.spot_1m_by_day.get(trade_date)
    if not raw1:
        return None
    expiry = window.expiry_by_day.get(trade_date)
    if expiry is None:
        return None

    tf = cfg.timeframe_min
    conf_tf = cfg.confirm_timeframe_min
    warmup1 = _prior_days_1m(window, trade_date, _WARMUP_DAYS)
    prior1 = _prior_session_1m(window, trade_date)

    dec_bars = _resample_spot_ist(raw1, tf)
    if not dec_bars:
        return None
    conf_bars = _resample_spot_ist(raw1, conf_tf)
    prior_dec = _resample_spot_ist(warmup1, tf) if warmup1 else []
    prior_conf = _resample_spot_ist(warmup1, conf_tf) if warmup1 else []

    _t_dec, ema_fast_dec, ema_slow_dec = _ema_series(
        dec_bars, prior_dec, cfg.ema_fast, cfg.ema_slow
    )
    t_conf, ema_fast_conf, ema_slow_conf = _ema_series(
        conf_bars, prior_conf, cfg.ema_fast, cfg.ema_slow
    )
    _st_t_dec, st_dir_dec = _st_series(dec_bars, prior_dec, cfg.st_period, cfg.st_mult)
    st_t_conf, st_dir_conf = _st_series(conf_bars, prior_conf, cfg.st_period, cfg.st_mult)

    vwap_times, vwap_vals = _session_vwap_series(raw1, cfg.vwap_source)

    # Day-constant levels from the prior session's HLC.
    cam_daily = _daily_camarilla(prior1)

    # Opening range strictly from the ``orb_start_ist``-stamped confirmation bar.
    orb_bar = _find_orb_bar(conf_bars, cfg.orb_start_ist)
    orb_high = float(orb_bar["high"]) if orb_bar else None
    orb_low = float(orb_bar["low"]) if orb_bar else None
    # The range is only knowable once its candle has closed; bars before that see
    # ``None`` so no decision can consult a level that had not formed yet.
    orb_ready_at = (
        datetime.combine(trade_date, cfg.orb_start_ist) + timedelta(minutes=cfg.orb_minutes)
    )

    day_chain: dict[str, dict[float, list]] = {}
    for opt in ("CE", "PE"):
        by_strike = window.chain_1m.get((trade_date, opt), {})
        day_chain[opt] = {stk: resample_ohlcv(bars, tf) for stk, bars in by_strike.items()}

    decision: list[IntradayDecisionBar] = []
    for i, b in enumerate(dec_bars):
        ist = _ist_of(b)
        o, h, lo, c = (
            float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        )
        # The session VWAP through this bar's close: the last 1m sample inside this
        # bucket, never a later one.
        vwap_cutoff = ist + timedelta(minutes=tf - 1)
        session_vwap = (
            _at(vwap_times, vwap_vals, vwap_cutoff) if vwap_times else None
        )
        orb_formed = ist >= orb_ready_at
        # A confirmation bar stamped T does not exist until T + conf_tf. Looking it up at
        # ``ist`` would read the 09:15-09:29 candle from the 09:15 decision bar — 15
        # minutes of future. Target its close instead, so only closed bars are visible;
        # this is also what makes the live path (which can only see closed bars)
        # reproducible bar for bar. See tests/test_intraday_parity.py.
        conf_cutoff = ist - timedelta(minutes=conf_tf)
        inputs = IntradayInputs(
            ist_dt=ist,
            spot=c,
            bar_high=h,
            bar_low=lo,
            ema9_5m=ema_fast_dec[i],
            ema20_5m=ema_slow_dec[i],
            ema9_prev_5m=ema_fast_dec[i - 1] if i > 0 else None,
            ema20_prev_5m=ema_slow_dec[i - 1] if i > 0 else None,
            ema9_15m=_at(t_conf, ema_fast_conf, conf_cutoff),
            ema20_15m=_at(t_conf, ema_slow_conf, conf_cutoff),
            st_5m_dir=st_dir_dec[i],
            st_15m_dir=_at(st_t_conf, st_dir_conf, conf_cutoff),
            session_vwap=session_vwap,
            orb_high=orb_high if orb_formed else None,
            orb_low=orb_low if orb_formed else None,
            cam=cam_daily,
            option_st_dir=None,  # resolved per held strike by the engine
        )
        decision.append(
            IntradayDecisionBar(ist_dt=ist, open=o, high=h, low=lo, close=c, inputs=inputs)
        )

    return IntradayDayData(
        trade_date=trade_date,
        expiry_date=expiry,
        decision_bars=decision,
        day_chain=day_chain,
        option_trend=OptionTrendReader(day_chain, cfg.st_period, cfg.st_mult),
        spot_open=float(dec_bars[0]["open"]),
        spot_close=float(dec_bars[-1]["close"]),
        orb_high=orb_high,
        orb_low=orb_low,
    )
