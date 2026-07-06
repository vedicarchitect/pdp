"""Load-once market data for config sweeps.

The sweep runs ~100 configs over the same window. Mongo is hit **once** here (raw 1-minute spot +
option chains for the whole window); each config then builds its per-day :class:`pdp.backtest.sim.DayData`
by resampling the cached 1-minute series to that config's timeframe in memory. This mirrors the
sub-minute single-run budget of ``backtest_multiday.py`` while amortising I/O across the grid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pdp.backtest.chain_loader import load_expiry_chain
from pdp.backtest.completeness import spot_completeness
from pdp.backtest.resample import resample_ohlcv
from pdp.backtest.sim import DayData
from pdp.instruments.expiry_calendar import nearest_real_expiry, real_expiries_from_option_bars

_IST = timedelta(hours=5, minutes=30)
NIFTY_SID = "13"


def biz_days(end: date, n: int) -> list[date]:
    """The ``n`` most recent weekdays ending at ``end`` (holidays fall out as no-data skips)."""
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def _resolve_expiry(cal: Any, d: date) -> date | None:
    """Legacy JSON-calendar fallback, used only when ``option_bars`` has no chain at all
    for the underlying (pre-ingest). See ``pdp.instruments.expiry_calendar`` for the
    generic, cadence-agnostic historical-expiry lookup used everywhere else.
    """
    if cal is not None:
        return cal.resolve_expiry(d, "WEEK", 1)
    return None


@dataclass
class WindowData:
    """Cached raw 1-minute data for a backtest window, resampled per-config on demand."""

    spot_1m_by_day: dict[date, list[dict]]              # IST trade-date -> raw market_bars docs (ts UTC)
    chain_1m: dict[tuple[date, str], dict[float, list]]  # (date, opt) -> {strike: 1m (dt,o,h,lo,c)}
    expiry_by_day: dict[date, date]
    valid_days: list[date] = field(default_factory=list)
    skipped: dict[date, str] = field(default_factory=dict)


def load_window(
    mdb: Any,
    cal: Any,
    days: list[date],
    *,
    security_id: str = NIFTY_SID,
    underlying: str = "NIFTY",
) -> WindowData:
    """Load raw 1-minute spot + option chains for ``days`` and run the completeness gate."""
    # ── Spot: one query for the whole range, bucketed by IST trade-date. ──
    spot_by_day: dict[date, list[dict]] = {}
    if days:
        lo = datetime(days[0].year, days[0].month, days[0].day, 0, 0, tzinfo=timezone.utc)
        hi = datetime(days[-1].year, days[-1].month, days[-1].day, 23, 59, tzinfo=timezone.utc)
        for b in mdb["market_bars"].find(
            {"metadata.security_id": security_id, "metadata.timeframe": "1m",
             "ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1):
            ts = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=timezone.utc)
            spot_by_day.setdefault((ts + _IST).date(), []).append(b)

    # ── Expiry per day, then one chain query per expiry (1-minute bars). ──
    # Expiries come dynamically from the real chains stored in option_bars (the scrip-master
    # truth, via pdp.instruments.expiry_calendar — the one shared expiry source) —
    # cadence-agnostic, correct for BANKNIFTY monthly / SENSEX Thursday / any regime change,
    # with NO hardcoded weekday. Days with no real expiry on or after them are simply not
    # traded (they fall out as no-chain skips); the legacy JSON-calendar fallback is used ONLY
    # when option_bars has no chain at all for the underlying (pre-ingest / legacy callers).
    real_expiries = real_expiries_from_option_bars(mdb, underlying)
    expiry_by_day: dict[date, date] = {}
    for d in days:
        if real_expiries:
            real = nearest_real_expiry(real_expiries, d)
            if real is not None:
                expiry_by_day[d] = real
            # else: no real expiry on/after this day → leave unmapped (day skipped, not faked)
        else:
            e = _resolve_expiry(cal, d)
            if e is not None:
                expiry_by_day[d] = e
    by_exp: dict[date, list[date]] = {}
    for d, e in expiry_by_day.items():
        by_exp.setdefault(e, []).append(d)
    chain_1m: dict[tuple[date, str], dict[float, list]] = {}
    for exp, tds in by_exp.items():
        store, _ = load_expiry_chain(mdb["option_bars"], exp, tds, tf_min=1, underlying=underlying)
        chain_1m.update(store)

    # ── Completeness gate (on the raw 1m spot series). A day is only tradeable if it has
    # BOTH complete spot data AND a resolved expiry — no expiry means no chain to trade. ──
    valid, skipped = [], {}
    for d in days:
        if d not in expiry_by_day:
            skipped[d] = "no_expiry"
            continue
        comp = spot_completeness(spot_by_day.get(d, []))
        if comp["ok"]:
            valid.append(d)
        else:
            skipped[d] = comp["reason"] or "incomplete"

    return WindowData(
        spot_1m_by_day=spot_by_day, chain_1m=chain_1m,
        expiry_by_day=expiry_by_day, valid_days=valid, skipped=skipped,
    )


def _resample_spot_ist(raw1: list[dict], tf: int) -> list[dict]:
    """Resample raw 1m spot docs on an **IST-anchored** grid, returning dicts with UTC ``ts``.

    Bucketing on IST-naive timestamps keeps spot and option series on the same grid for every
    timeframe (critical at 60m, where the IST 05:30 offset is not a whole multiple of the bucket).
    For 3/5/15/30m the result is identical to UTC-grid resampling (the offset divides evenly).
    """
    tuples = []
    for d in raw1:
        ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=timezone.utc)
        ist = (ts + _IST).replace(tzinfo=None)
        tuples.append((ist, float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"])))
    tuples.sort(key=lambda b: b[0])
    out = []
    for (ist_dt, o, h, lo, c) in resample_ohlcv(tuples, tf):
        out.append({"ts": (ist_dt - _IST).replace(tzinfo=timezone.utc),
                    "open": o, "high": h, "low": lo, "close": c})
    return out


def _prior_session_1m(window: WindowData, trade_date: date, max_lookback: int = 7) -> list[dict]:
    """Raw 1m spot for the most recent trading day before ``trade_date`` (>= 60 bars), else []."""
    d = trade_date - timedelta(days=1)
    for _ in range(max_lookback):
        bars = window.spot_1m_by_day.get(d)
        if bars and len(bars) >= 60:
            return bars
        d -= timedelta(days=1)
    return []


def build_day_data(window: WindowData, cfg, trade_date: date) -> DayData | None:
    """Resample the cached 1m data to ``cfg.timeframe_min`` and assemble a ``DayData``."""
    raw1 = window.spot_1m_by_day.get(trade_date)
    if not raw1:
        return None
    tf = cfg.timeframe_min
    nifty_bars = _resample_spot_ist(raw1, tf)
    prior = _prior_session_1m(window, trade_date)
    prior_bars = _resample_spot_ist(prior, tf) if prior else []

    day_chain: dict[str, dict[float, list]] = {}
    for opt in ("CE", "PE"):
        series_by_strike = window.chain_1m.get((trade_date, opt), {})
        day_chain[opt] = {stk: resample_ohlcv(bars, tf) for stk, bars in series_by_strike.items()}

    return DayData(
        trade_date=trade_date,
        expiry_date=window.expiry_by_day[trade_date],
        nifty_bars=nifty_bars,
        prior_session_bars=prior_bars,
        day_chain=day_chain,
    )
