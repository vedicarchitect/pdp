"""Batch option-chain pre-loader for the backtest hot path.

The per-bar backtest reader issues one ``option_bars.find()`` per strike change and fans out
extra probes when a strike is missing — O(signal bars) round-trips. This module replaces that
with **one query per expiry**: it pulls every stored strike for an expiry across all of its
trade-days in a single indexed scan (``(underlying, expiry_date, option_type, ts)``), buckets
the bars by ``(trade_date, option_type, strike)`` in memory, and resamples each series once to
the signal timeframe. The backtest then serves exact-strike and nearest-strike lookups from RAM.

Returned bars match the per-bar reader's shape exactly: IST-naive ``(dt, open, high, low, close)``
tuples resampled to ``tf_min`` via :func:`pdp.backtest.resample.resample_ohlcv`, so replayed
trades and P&L are unchanged — only the data-access path differs.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pdp.backtest.resample import resample_ohlcv

IST = timedelta(hours=5, minutes=30)

# store[(trade_date, option_type)] -> {strike: [(dt, o, h, lo, c), ...]}
ChainStore = dict[tuple[date, str], dict[float, list]]


def load_expiry_chain(
    col: Any,
    expiry_date: date,
    trade_dates: list[date],
    *,
    tf_min: int,
    underlying: str = "NIFTY",
    timeframe: str = "1m",
) -> tuple[ChainStore, int]:
    """Load all option bars for one expiry across ``trade_dates`` in a single query.

    Returns ``(store, n_queries)`` where ``store`` maps ``(trade_date, option_type)`` to a
    ``{strike: resampled_bars}`` dict and ``n_queries`` is 1 (or 0 when ``trade_dates`` is empty).
    A NSE session falls on the same UTC calendar date as its IST date, so bucketing by the
    IST-converted timestamp's date is exact.
    """
    if not trade_dates:
        return {}, 0

    expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, tzinfo=UTC)
    lo, hi = min(trade_dates), max(trade_dates)
    lo_utc = datetime(lo.year, lo.month, lo.day, 0, 0, tzinfo=UTC)
    hi_utc = datetime(hi.year, hi.month, hi.day, 23, 59, tzinfo=UTC)

    cursor = col.find(
        {
            "underlying": underlying,
            "expiry_date": expiry_dt,
            "timeframe": timeframe,
            "ts": {"$gte": lo_utc, "$lte": hi_utc},
        },
        {"ts": 1, "open": 1, "high": 1, "low": 1, "close": 1,
         "strike": 1, "option_type": 1, "_id": 0},
    )

    # Bucket raw 1m bars by (IST trade-date, option_type, strike); resample once per series.
    raw: dict[tuple[date, str, float], list] = {}
    for doc in cursor:
        ts = doc["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ist_dt = (ts + IST).replace(tzinfo=None)
        key = (ist_dt.date(), doc["option_type"].upper(), float(doc["strike"]))
        raw.setdefault(key, []).append(
            (ist_dt, float(doc["open"]), float(doc["high"]),
             float(doc["low"]), float(doc["close"])),
        )

    store: ChainStore = {}
    for (td, opt, strike), bars in raw.items():
        bars.sort(key=lambda b: b[0])
        store.setdefault((td, opt), {})[strike] = resample_ohlcv(bars, tf_min)
    return store, 1


def lookup_strike(
    store: ChainStore,
    trade_date: date,
    opt_type: str,
    target_strike: float,
    *,
    band: int,
    step: int,
) -> tuple[float | None, list]:
    """Exact strike, then nearest within ``band`` grid steps, from the pre-loaded ``store``.

    Searches outward (``target+step``, ``target-step``, ``+2*step`` …) to mirror the per-bar
    reader's fallback order. Returns ``(actual_strike, bars)`` or ``(None, [])`` if nothing in band.
    """
    day = store.get((trade_date, opt_type.upper()))
    if not day:
        return None, []
    t = float(target_strike)
    if day.get(t):
        return t, day[t]
    for s in range(1, band + 1):
        for cand in (t + s * step, t - s * step):
            if day.get(cand):
                return cand, day[cand]
    return None, []
