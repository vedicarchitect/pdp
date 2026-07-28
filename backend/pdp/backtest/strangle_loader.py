"""Assemble per-bar multi-timeframe ``BiasInputs`` for the directional-strangle backtest.

This is the bridge between the cached Mongo window (``day_loader.WindowData``) and the pure
``strangle_sim`` engine. For one trade day it:
  * resamples 1m spot to the decision timeframe (e.g. 5m) and to 15m / 1h,
  * runs ``EMATracker`` per timeframe (warmed with the prior session) for 9/20/50 EMAs,
  * computes daily & weekly Camarilla levels and prior-day/week swing levels from prior-period HLC,
  * tracks the 15m opening range,
  * joins the India VIX series (resampled to 5m) for the gate,
and emits a ``StrangleDayData`` whose ``decision_bars`` each carry a fully-populated ``BiasInputs``.

PCR per bar (option-OI based) is left as ``None`` here — the cached chain carries OHLC only; an
OI-aware chain load is a follow-up. The bias engine treats a missing signal as simply absent.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta

from pdp.backtest.day_loader import WindowData, _prior_session_1m, _resample_spot_ist
from pdp.backtest.resample import resample_ohlcv
from pdp.backtest.sim import resolve_from_chain
from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_sim import DecisionBar, StrangleDayData
from pdp.indicators.ema import EMATracker
from pdp.indicators.psar import ParabolicSARTracker
from pdp.indicators.supertrend import SuperTrendTracker
from pdp.signals.bias import (
    BiasInputs,
    CamLevels,
    SeriesInputs,
    TimeframeEMA,
    tf_ema_from_values,
)

_IST = timedelta(hours=5, minutes=30)
_EMA_PERIODS = [9, 20, 50]


def _ema_series(
    bars: list[dict], prior_bars: list[dict]
) -> tuple[list[datetime], list[dict[int, float]]]:
    """EMA(9/20/50) per bar (IST times), warmed with the prior session."""
    tr = EMATracker(periods=_EMA_PERIODS)
    for wb in prior_bars:
        wts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
        tr.update(wb["high"], wb["low"], wb["close"], 0.0, wts)
    times: list[datetime] = []
    vals: list[dict[int, float]] = []
    for b in bars:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        ist = (ts + _IST).replace(tzinfo=None)
        st = tr.update(b["high"], b["low"], b["close"], 0.0, ts)
        times.append(ist)
        vals.append(dict(st.values) if st is not None else {})
    return times, vals


def _asof(times: list[datetime], target: datetime) -> int | None:
    """Index of the latest entry at or before ``target`` (no look-ahead), else None."""
    i = bisect_right(times, target) - 1
    return i if i >= 0 else None


def _tf_ema_at(times: list[datetime], vals: list[dict[int, float]], t: datetime,
               price: float) -> TimeframeEMA | None:
    i = _asof(times, t)
    if i is None:
        return None
    return tf_ema_from_values(vals[i], price)


def _st_psar_series(
    bars: list[dict], prior_bars: list[dict], cfg: StrangleConfig
) -> tuple[list[datetime], list[tuple[int, int] | None], list[int | None]]:
    """Per-bar SuperTrend-agreement + PSAR reads for a spot timeframe (IST times), warmed
    with the prior window.

    ``st_pair = (dir_ST(fast), dir_ST(slow))`` (``None`` until both variants seed); ``psar_dir``
    is the SAR direction (``None`` until the SAR seeds). Mirrors ``_ema_series`` so the same
    warm-then-replay tracker state feeds the bias engine on both the backtest and live paths.
    """
    st_fast = SuperTrendTracker(cfg.st_fast_period, cfg.st_fast_mult)
    st_slow = SuperTrendTracker(cfg.st_slow_period, cfg.st_slow_mult)
    psar = ParabolicSARTracker(cfg.psar_step, cfg.psar_max_step)
    for wb in prior_bars:
        wts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
        st_fast.update(wb["high"], wb["low"], wb["close"], wts)
        st_slow.update(wb["high"], wb["low"], wb["close"], wts)
        psar.update(wb["high"], wb["low"], wb["close"], 0.0, wts)
    times: list[datetime] = []
    st_pairs: list[tuple[int, int] | None] = []
    psar_dirs: list[int | None] = []
    for b in bars:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        ist = (ts + _IST).replace(tzinfo=None)
        sf = st_fast.update(b["high"], b["low"], b["close"], ts)
        ss = st_slow.update(b["high"], b["low"], b["close"], ts)
        ps = psar.update(b["high"], b["low"], b["close"], 0.0, ts)
        times.append(ist)
        st_pairs.append(
            (sf.direction, ss.direction) if (sf is not None and ss is not None) else None
        )
        psar_dirs.append(ps.direction if ps is not None else None)
    return times, st_pairs, psar_dirs


def _at(times: list[datetime], vals: list, t: datetime):
    """As-of lookup into a parallel (times, vals) pair; None if nothing at/before ``t``."""
    i = _asof(times, t)
    return vals[i] if i is not None else None


def _option_series_reads(
    sbars: list, cfg: StrangleConfig
) -> tuple[list[datetime], list[SeriesInputs]]:
    """Replay EMA/ST/PSAR over one option strike's own ``(dt, o, h, lo, c)`` decision-tf bars.

    No warmup prefix: an option contract's bars only exist for the trade day, so EMA(50) /
    SuperTrend seed intraday and each sub-read abstains (contributes ``None``) until it does —
    ``_series_trend`` combines whatever is present. Returns parallel (ist_times, reads).
    """
    tr_ema = EMATracker(periods=_EMA_PERIODS)
    st_fast = SuperTrendTracker(cfg.st_fast_period, cfg.st_fast_mult)
    st_slow = SuperTrendTracker(cfg.st_slow_period, cfg.st_slow_mult)
    psar = ParabolicSARTracker(cfg.psar_step, cfg.psar_max_step)
    times: list[datetime] = []
    reads: list[SeriesInputs] = []
    for row in sbars:
        dt, _o, h, lo, c = row[0], row[1], row[2], row[3], row[4]
        es = tr_ema.update(h, lo, c, 0.0, dt)
        sf = st_fast.update(h, lo, c, dt)
        ss = st_slow.update(h, lo, c, dt)
        ps = psar.update(h, lo, c, 0.0, dt)
        ema_read = tf_ema_from_values(dict(es.values) if es is not None else None, float(c))
        st_pair = (sf.direction, ss.direction) if (sf is not None and ss is not None) else None
        reads.append(SeriesInputs(ema=ema_read, st=st_pair, psar=ps.direction if ps is not None else None))
        times.append(dt)
    return times, reads


def _hlc(bars: list[dict]) -> tuple[float, float, float] | None:
    """(high, low, close) over a set of 1m docs."""
    if not bars:
        return None
    hi = max(float(b["high"]) for b in bars)
    lo = min(float(b["low"]) for b in bars)
    cl = float(bars[-1]["close"])
    return hi, lo, cl


def _camarilla(hlc: tuple[float, float, float] | None) -> CamLevels | None:
    if hlc is None:
        return None
    h, lo, c = hlc
    rng = h - lo
    return CamLevels(
        r3=c + rng * 1.1 / 4.0, r4=c + rng * 1.1 / 2.0,
        s3=c - rng * 1.1 / 4.0, s4=c - rng * 1.1 / 2.0,
    )


def _prior_week_1m(window: WindowData, trade_date: date) -> list[dict]:
    """All 1m spot docs from the most recent ISO week before ``trade_date``'s week."""
    cur_week = trade_date.isocalendar()[:2]
    out: list[dict] = []
    target: tuple[int, int] | None = None
    for d in sorted(window.spot_1m_by_day, reverse=True):
        if d >= trade_date:
            continue
        wk = d.isocalendar()[:2]
        if wk == cur_week:
            continue
        if target is None:
            target = wk
        if wk == target:
            out.extend(window.spot_1m_by_day[d])
        elif wk < target:
            break
    return out


# EMA(50) on the 1h timeframe needs ~50 hourly bars (~8 trading days) to seed, so the EMA
# trackers are warmed with a multi-day prior window — not just the immediately-prior session.
_EMA_WARMUP_DAYS = 20


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


def build_strangle_day(
    window: WindowData,
    cfg: StrangleConfig,
    trade_date: date,
    vix_1m_by_day: dict[date, list[dict]] | None = None,
    pcr_by_day: dict[date, list[tuple[datetime, float]]] | None = None,
) -> StrangleDayData | None:
    """Assemble one trade day of decision bars with multi-timeframe ``BiasInputs``."""
    raw1 = window.spot_1m_by_day.get(trade_date)
    if not raw1:
        return None

    tf = cfg.timeframe_min
    prior1 = _prior_session_1m(window, trade_date)
    warmup1 = _prior_days_1m(window, trade_date, _EMA_WARMUP_DAYS)

    dec_bars = _resample_spot_ist(raw1, tf)
    bars_5 = dec_bars
    bars_15 = _resample_spot_ist(raw1, 15)
    bars_60 = _resample_spot_ist(raw1, 60)
    prior_5 = _resample_spot_ist(warmup1, tf) if warmup1 else []
    prior_15 = _resample_spot_ist(warmup1, 15) if warmup1 else []
    prior_60 = _resample_spot_ist(warmup1, 60) if warmup1 else []

    t5, v5 = _ema_series(bars_5, prior_5)
    t15, v15 = _ema_series(bars_15, prior_15)
    t60, v60 = _ema_series(bars_60, prior_60)

    # SuperTrend-agreement + PSAR reads per timeframe (warmed with the same prefix as EMA).
    st5_t, st5_pairs, ps5_dirs = _st_psar_series(bars_5, prior_5, cfg)
    st15_t, st15_pairs, ps15_dirs = _st_psar_series(bars_15, prior_15, cfg)
    st60_t, st60_pairs, ps60_dirs = _st_psar_series(bars_60, prior_60, cfg)

    # Day-constant levels from prior period HLC.
    cam_daily = _camarilla(_hlc(prior1))
    cam_weekly = _camarilla(_hlc(_prior_week_1m(window, trade_date)))
    prior_hlc = _hlc(prior1)
    pwh_hlc = _hlc(_prior_week_1m(window, trade_date))
    pdh = prior_hlc[0] if prior_hlc else None
    pdl = prior_hlc[1] if prior_hlc else None
    pwh = pwh_hlc[0] if pwh_hlc else None
    pwl = pwh_hlc[1] if pwh_hlc else None

    # Opening range = first 15m bar of the day.
    orb_high = orb_low = None
    if bars_15:
        orb_high = float(bars_15[0]["high"])
        orb_low = float(bars_15[0]["low"])

    # VIX series for the day, resampled to the decision timeframe.
    vix_times, vix_close, vix_open, vix_high = _vix_for_day(vix_1m_by_day, trade_date, tf)

    # PCR series for the day (1m OI-based; None when not loaded).
    pcr_day = pcr_by_day.get(trade_date) if pcr_by_day else None
    pcr_times = [t for t, _ in pcr_day] if pcr_day else []
    pcr_vals = [v for _, v in pcr_day] if pcr_day else []

    day_chain: dict[str, dict[float, list]] = {}
    for opt in ("CE", "PE"):
        series_by_strike = window.chain_1m.get((trade_date, opt), {})
        day_chain[opt] = {stk: resample_ohlcv(bars, tf) for stk, bars in series_by_strike.items()}

    # ATM CE/PE 5m trend read: replayed EMA/ST/PSAR over each ATM strike's own bars. Populated
    # only when the ATM vote carries weight (it is otherwise inert, so building it would be pure
    # overhead). Reads are memoised per resolved chain strike so a strike that is ATM across many
    # bars is replayed once. Mirrors the live path, which gates the same read on `w_atm > 0`.
    populate_atm = cfg.atm_trend_enabled and cfg.weights.w_atm > 0
    step = cfg.strike_step
    _atm_cache: dict[tuple[str, float], tuple[list[datetime], list[SeriesInputs]]] = {}

    def _atm_read_at(opt: str, spot: float, t: datetime) -> SeriesInputs | None:
        atm = round(spot / step) * step
        strike, sbars = resolve_from_chain(day_chain, opt, float(atm), step, band=2)
        if strike is None or not sbars:
            return None
        key = (opt, strike)
        if key not in _atm_cache:
            _atm_cache[key] = _option_series_reads(sbars, cfg)
        entry_times, entry_reads = _atm_cache[key]
        return _at(entry_times, entry_reads, t)

    decision: list[DecisionBar] = []
    for b in dec_bars:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        ist = (ts + _IST).replace(tzinfo=None)
        o, h, lo, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])

        vix_i = _asof(vix_times, ist) if vix_times else None
        vix_now = vix_close[vix_i] if vix_i is not None else None
        vix_recent = vix_close[max(0, vix_i - 2): vix_i + 1] if vix_i is not None else []

        pcr_i = _asof(pcr_times, ist) if pcr_times else None
        pcr = pcr_vals[pcr_i] if pcr_i is not None else None

        bias = BiasInputs(
            spot=c,
            ema_1h=_tf_ema_at(t60, v60, ist, c),
            ema_15m=_tf_ema_at(t15, v15, ist, c),
            ema_5m=_tf_ema_at(t5, v5, ist, c),
            cam_daily=cam_daily,
            cam_weekly=cam_weekly,
            pdh=pdh, pdl=pdl, pwh=pwh, pwl=pwl,
            orb_high=orb_high, orb_low=orb_low,
            st_5m=_at(st5_t, st5_pairs, ist),
            st_15m=_at(st15_t, st15_pairs, ist),
            st_1h=_at(st60_t, st60_pairs, ist),
            psar_5m=_at(st5_t, ps5_dirs, ist),
            psar_15m=_at(st15_t, ps15_dirs, ist),
            psar_1h=_at(st60_t, ps60_dirs, ist),
            atm_ce_5m=_atm_read_at("CE", c, ist) if populate_atm else None,
            atm_pe_5m=_atm_read_at("PE", c, ist) if populate_atm else None,
            pcr=pcr,
            vix_now=vix_now, vix_day_open=vix_open, vix_day_high=vix_high,
            vix_recent=list(vix_recent),
        )
        decision.append(DecisionBar(ist_dt=ist, open=o, high=h, low=lo, close=c, bias=bias))

    # Raw 1m spot in IST, in the same (dt, o, h, l, c) tuple shape `day_chain` uses. The
    # engine never reads this — it decides on `dec_bars` (cfg.timeframe_min). It exists so
    # the EOD walkthrough can render a real per-minute ribbon between decision bars.
    spot_1m: list[tuple[datetime, float, float, float, float]] = []
    for b in raw1:
        ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        spot_1m.append((
            (ts + _IST).replace(tzinfo=None),
            float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]),
        ))

    return StrangleDayData(
        trade_date=trade_date,
        expiry_date=window.expiry_by_day[trade_date],
        decision_bars=decision,
        day_chain=day_chain,
        nifty_open=float(dec_bars[0]["open"]) if dec_bars else 0.0,
        nifty_close=float(dec_bars[-1]["close"]) if dec_bars else 0.0,
        spot_1m=spot_1m,
    )


def load_pcr_window(
    option_bars_col: object,
    expiry_by_day: dict[date, date],
    trade_dates: list[date],
    underlying: str = "NIFTY",
) -> dict[date, list[tuple[datetime, float]]]:
    """Aggregate CE/PE OI per minute and compute PCR for each trade date.

    Returns ``{trade_date: [(ist_dt, pcr), ...]}`` ordered by timestamp.
    Uses a single MongoDB aggregation per calendar quarter to avoid scanning 42M+ rows.
    """
    if not trade_dates:
        return {}

    chunks: dict[tuple[int, int], list[date]] = {}
    for d in trade_dates:
        chunks.setdefault((d.year, (d.month - 1) // 3), []).append(d)

    pcr_by_day: dict[date, list[tuple[datetime, float]]] = {}

    for _, chunk_days in sorted(chunks.items()):
        expiries = list({expiry_by_day[d] for d in chunk_days if d in expiry_by_day})
        lo = datetime(min(chunk_days).year, min(chunk_days).month, min(chunk_days).day,
                      0, 0, tzinfo=UTC)
        hi = datetime(max(chunk_days).year, max(chunk_days).month, max(chunk_days).day,
                      23, 59, tzinfo=UTC)
        expiry_dts = [datetime(e.year, e.month, e.day, tzinfo=UTC) for e in expiries]

        pipeline = [
            {"$match": {
                "underlying": underlying,
                "expiry_date": {"$in": expiry_dts},
                "timeframe": "1m",
                "ts": {"$gte": lo, "$lte": hi},
                "oi": {"$exists": True, "$gt": 0},
            }},
            {"$group": {
                "_id": {"ts": "$ts", "option_type": "$option_type"},
                "total_oi": {"$sum": "$oi"},
            }},
            {"$sort": {"_id.ts": 1}},
        ]

        # Pivot (ts, option_type, total_oi) -> PCR per minute.
        oi_raw: dict[datetime, dict[str, float]] = {}
        for doc in option_bars_col.aggregate(pipeline, allowDiskUse=True):
            ts_raw = doc["_id"]["ts"]
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
            opt = doc["_id"]["option_type"].upper()
            oi_raw.setdefault(ts, {})[opt] = float(doc["total_oi"])

        for ts_utc, sides in sorted(oi_raw.items()):
            ist = (ts_utc + _IST).replace(tzinfo=None)
            trade_date = ist.date()
            ce_oi = sides.get("CE", 0.0)
            pe_oi = sides.get("PE", 0.0)
            if ce_oi > 0:
                pcr_by_day.setdefault(trade_date, []).append((ist, pe_oi / ce_oi))

    return pcr_by_day


def _vix_for_day(
    vix_1m_by_day: dict[date, list[dict]] | None, trade_date: date, tf: int
) -> tuple[list[datetime], list[float], float | None, float | None]:
    """Return (ist_times, closes, day_open, day_high) for VIX resampled to ``tf``."""
    if not vix_1m_by_day:
        return [], [], None, None
    raw = vix_1m_by_day.get(trade_date)
    if not raw:
        return [], [], None, None
    res = _resample_spot_ist(raw, tf)
    times = [
        ((b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)) + _IST).replace(tzinfo=None)
        for b in res
    ]
    closes = [float(b["close"]) for b in res]
    day_open = float(res[0]["open"]) if res else None
    day_high = max(float(b["high"]) for b in res) if res else None
    return times, closes, day_open, day_high
