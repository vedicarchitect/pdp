"""Tests for scripts/backfill_levels.py's session-anchored HLC helpers and monthly path.

Uses a lightweight in-memory pymongo-style stub (sync, mirroring the real aggregation
`$match`/`$group` shape) instead of a real MongoDB, so these run offline.
"""
from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from backfill_levels import (
    _build_level_doc,
    _fetch_day_hlc_sync,
    _fetch_range_hlc_sync,
    _first_trading_days_of_month,
)


class _FakeSyncCollection:
    """Sync stub evaluating the real `$match`(ts range + tf)/`$group`(max/min/last/count)
    shape against in-memory 1m bar docs — same approach as the async fake in
    tests/indicators/test_session_hlc.py, adapted for pymongo's sync `.aggregate()`."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def aggregate(self, pipeline: list[dict]):
        match = pipeline[0]["$match"]
        sid = match["metadata.security_id"]
        tf = match["metadata.timeframe"]
        lo = match["ts"]["$gte"]
        hi = match["ts"]["$lt"]
        rows = [
            d for d in self._docs
            if d["metadata"]["security_id"] == sid
            and d["metadata"]["timeframe"] == tf
            and lo <= d["ts"] < hi
        ]
        if not rows:
            return []
        rows_sorted = sorted(rows, key=lambda d: d["ts"])
        return [{
            "h": max(d["high"] for d in rows_sorted),
            "l": min(d["low"] for d in rows_sorted),
            "c": rows_sorted[-1]["close"],
            "count": len(rows_sorted),
        }]


def _bar(day: date, hh: int, mm: int, high: float, low: float, close: float) -> dict:
    return {
        "ts": datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC),
        "metadata": {"security_id": "13", "timeframe": "1m"},
        "high": high,
        "low": low,
        "close": close,
    }


def _full_session_bars(day: date, base: float) -> list[dict]:
    """>=10 in-session 1m bars so `_fetch_day_hlc_sync`'s min-count guard passes."""
    return [
        _bar(day, 3, 45 + i, base + i, base + i - 5, base + i - 1)
        for i in range(12)
    ]


def test_fetch_day_hlc_sync_excludes_out_of_session_bad_tick() -> None:
    """Regression for the PMH bug: a pre-open spike must not affect the day's high."""
    day = date(2026, 6, 29)
    docs = [
        _bar(day, 3, 30, high=24361.1, low=24361.1, close=24361.1),  # pre-open, excluded
        *_full_session_bars(day, base=24070.0),
    ]
    col = _FakeSyncCollection(docs)

    hlc = _fetch_day_hlc_sync(col, "13", day)

    assert hlc is not None
    h, _lo, _c = hlc
    assert h == 24070.0 + 11  # max of the in-session bars only
    assert h < 24361.1


def test_fetch_range_hlc_sync_combines_days_for_monthly() -> None:
    """The monthly path aggregates per-day session HLC across the whole prior month —
    max of daily highs, min of daily lows, last trading day's close."""
    d1 = date(2026, 6, 25)
    d2 = date(2026, 6, 29)
    docs = [
        *_full_session_bars(d1, base=24250.0),  # day high = 24261
        _bar(d2, 3, 30, high=24361.1, low=24361.1, close=24361.1),  # pre-open spike, excluded
        *_full_session_bars(d2, base=24060.0),  # day high = 24071
    ]
    col = _FakeSyncCollection(docs)

    hlc = _fetch_range_hlc_sync(col, "13", date(2026, 6, 1), date(2026, 6, 30))

    assert hlc is not None
    h, _lo, c = hlc
    assert h == 24261.0  # NOT 24361.1 — the pre-open spike must not leak into the monthly high
    assert c == 24060.0 + 11 - 1  # last trading day's (d2) close


def test_build_level_doc_monthly_shape() -> None:
    doc = _build_level_doc(
        "13", "NIFTY", "monthly", date(2026, 7, 1),
        24261.6, 24000.2, 24211.15,
        date(2026, 6, 1), date(2026, 6, 30),
    )
    assert doc["period"] == "monthly"
    assert doc["source"]["h"] == 24261.6
    assert doc["source"]["window_start"] == "2026-06-01"
    assert doc["source"]["window_end"] == "2026-06-30"
    assert set(doc["camarilla"].keys()) == {"pp", "r3", "r4", "s3", "s4"}


def test_first_trading_days_of_month_one_per_month() -> None:
    days = [
        date(2026, 6, 29), date(2026, 6, 30),
        date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3),
        date(2026, 8, 3),
    ]
    result = _first_trading_days_of_month(days)
    assert result == [date(2026, 6, 29), date(2026, 7, 1), date(2026, 8, 3)]
