"""Resample 1-minute source bars to a coarser signal timeframe.

The live platform builds every timeframe simultaneously from the tick stream via
``BarAggregator``; a native 5m feed is never used. Backtests therefore fetch 1-minute
bars and resample here so the replayed series is constructed by the same rule:
open = first, high = max, low = min, close = last, volume = sum, on aligned boundaries.

The IST offset (5:30) is a whole multiple of 5 minutes, so 5m/15m/30m boundaries align
identically whether the timestamps are UTC or IST-naive.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

TF_MIN_DEFAULT = 5


def floor_min(dt: datetime, tf_min: int) -> datetime:
    """Truncate ``dt`` down to the start of its ``tf_min``-minute bucket."""
    return dt.replace(second=0, microsecond=0, minute=(dt.minute // tf_min) * tf_min)


def resample_ohlcv(bars, tf_min: int = TF_MIN_DEFAULT):
    """Resample sorted IST-naive ``(dt, o, h, lo, c)`` tuples to a coarser timeframe."""
    if tf_min <= 1 or not bars:
        return list(bars)
    buckets: dict[datetime, list] = {}
    order: list[datetime] = []
    for (dt, o, h, lo, c) in bars:
        b = floor_min(dt, tf_min)
        if b not in buckets:
            buckets[b] = [b, o, h, lo, c]
            order.append(b)
        else:
            agg = buckets[b]
            agg[2] = max(agg[2], h)
            agg[3] = min(agg[3], lo)
            agg[4] = c
    return [tuple(buckets[b]) for b in sorted(order)]


def records_from_data(data: dict[str, Any]) -> list[tuple]:
    """Dhan parallel-array data dict -> sorted ``[(ts_utc, o, h, lo, c, vol, oi, iv)]``."""
    opens = data["open"]
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    vols = data.get("volume", [])
    ois = data.get("oi", [])
    ivs = data.get("iv", [])
    tss = data.get("timestamp", data.get("start_Time", []))
    recs: list[tuple] = []
    for i in range(len(closes)):
        if not closes[i] or i >= len(tss):
            continue
        ts = tss[i]
        if isinstance(ts, (int, float)):
            ts_utc = datetime.fromtimestamp(ts, tz=UTC)
        else:
            try:
                ts_utc = datetime.fromisoformat(str(ts))
                ts_utc = ts_utc.replace(tzinfo=UTC) if ts_utc.tzinfo is None else ts_utc.astimezone(UTC)
            except ValueError:
                continue
        recs.append((
            ts_utc, float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i]),
            int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
            int(ois[i]) if i < len(ois) and ois[i] is not None else 0,
            float(ivs[i]) if i < len(ivs) and ivs[i] is not None else 0.0,
        ))
    recs.sort(key=lambda r: r[0])
    return recs


def resample_data_dict(data: dict[str, Any], tf_min: int = TF_MIN_DEFAULT) -> dict[str, Any]:
    """Resample a Dhan data dict (with volume/oi/iv) to a coarser timeframe.

    Returns a data dict with epoch-second ``timestamp`` so downstream parse/persist code
    consumes it unchanged. open=first, high=max, low=min, close=last, volume=sum, oi/iv=last.
    """
    recs = records_from_data(data)
    buckets: dict[datetime, list] = {}
    order: list[datetime] = []
    for ts, o, h, lo, c, v, oi, iv in recs:
        b = floor_min(ts, tf_min) if tf_min > 1 else ts
        if b not in buckets:
            buckets[b] = [b, o, h, lo, c, v, oi, iv]
            order.append(b)
        else:
            agg = buckets[b]
            agg[2] = max(agg[2], h)
            agg[3] = min(agg[3], lo)
            agg[4] = c
            agg[5] += v
            agg[6] = oi
            agg[7] = iv
    out: dict[str, list] = {
        k: [] for k in ("timestamp", "open", "high", "low", "close", "volume", "oi", "iv")
    }
    for b in sorted(order):
        a = buckets[b]
        out["timestamp"].append(int(a[0].timestamp()))
        out["open"].append(a[1])
        out["high"].append(a[2])
        out["low"].append(a[3])
        out["close"].append(a[4])
        out["volume"].append(a[5])
        out["oi"].append(a[6])
        out["iv"].append(a[7])
    return out


def resample_mongo_bars(docs, tf_min: int = TF_MIN_DEFAULT) -> list[dict[str, Any]]:
    """Resample MongoDB bar docs (``ts`` UTC, open/high/low/close) to a coarser timeframe."""
    norm = []
    for d in docs:
        ts = d["ts"]
        ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        norm.append((ts, float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"])))
    norm.sort(key=lambda r: r[0])
    if tf_min <= 1:
        return [{"ts": ts, "open": o, "high": h, "low": lo, "close": c} for ts, o, h, lo, c in norm]
    buckets: dict[datetime, dict] = {}
    order: list[datetime] = []
    for ts, o, h, lo, c in norm:
        b = floor_min(ts, tf_min)
        if b not in buckets:
            buckets[b] = {"ts": b, "open": o, "high": h, "low": lo, "close": c}
            order.append(b)
        else:
            agg = buckets[b]
            agg["high"] = max(agg["high"], h)
            agg["low"] = min(agg["low"], lo)
            agg["close"] = c
    return [buckets[b] for b in sorted(order)]
