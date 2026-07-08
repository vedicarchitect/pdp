"""Tests for the per-underlying, per-family coverage module (pdp.warehouse.coverage).

Uses lightweight async stubs for the Motor collections instead of a real MongoDB, so these run
offline. `_options_family` is tested by monkeypatching its blocking `_options_gaps_sync` helper
(the pymongo aggregation contract itself is already covered by tests/test_gap_backfill.py, which
`days_missing` is reused from directly).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

import pdp.warehouse.coverage as cov


class _AsyncCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for row in self._rows:
            yield row


class _FakeCollection:
    """Stub for an AsyncIOMotorCollection: aggregate/find return async cursors; find_one is async."""

    def __init__(self, *, agg_rows: list[dict] | None = None, docs: list[dict] | None = None) -> None:
        self._agg_rows = agg_rows or []
        self._docs = sorted(docs or [], key=lambda d: d.get("ts") or d.get("session_date"))

    def aggregate(self, pipeline):
        return _AsyncCursor(self._agg_rows)

    def find(self, match, projection=None):
        lo = match.get("session_date", {}).get("$gte")
        hi = match.get("session_date", {}).get("$lte")
        rows = [d for d in self._docs if lo <= d["session_date"] <= hi]
        return _AsyncCursor(rows)

    async def find_one(self, match, projection=None, sort=None):
        if not self._docs:
            return None
        reverse = bool(sort and sort[0][1] == -1)
        return self._docs[-1] if reverse else self._docs[0]


class _FakeMongoDb:
    def __init__(self, **cols: _FakeCollection) -> None:
        self._cols = cols

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._cols[name]


def _ist_ts(day: date, hh: int = 4, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm)  # UTC-naive, matches market_bars writer


async def test_spot_gaps_flags_days_with_no_bars():
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    present_day = date(2026, 1, 6)
    agg_rows = [{"_id": datetime(present_day.year, present_day.month, present_day.day), "n": 375}]
    docs = [{"ts": _ist_ts(present_day)}]
    mongo_db = _FakeMongoDb(market_bars=_FakeCollection(agg_rows=agg_rows, docs=docs))

    summary, gaps = await cov._spot_gaps(mongo_db, "13", days)

    assert gaps == {date(2026, 1, 5), date(2026, 1, 7)}
    assert summary["covered_days"] == 1
    assert summary["total_days"] == 3
    assert summary["gap_ranges"]  # non-empty, collapsed ranges present


async def test_spot_gaps_empty_days_returns_empty_family():
    mongo_db = _FakeMongoDb(market_bars=_FakeCollection())
    summary, gaps = await cov._spot_gaps(mongo_db, "13", [])
    assert gaps == set()
    assert summary["total_days"] == 0
    assert summary["coverage_pct"] == 0.0


async def test_levels_family_gap_days_from_index_levels():
    days = [date(2026, 1, 5), date(2026, 1, 6)]
    docs = [{"session_date": "2026-01-05"}]
    mongo_db = _FakeMongoDb(index_levels=_FakeCollection(docs=docs))

    summary, gaps = await cov._levels_family(mongo_db, "NIFTY", "weekly", days)

    assert gaps == {date(2026, 1, 6)}
    assert summary["covered_days"] == 1


async def test_underlying_coverage_rejects_unsupported_underlying():
    mongo_db = _FakeMongoDb()
    settings = object()
    with pytest.raises(ValueError, match="MIDCAP"):
        await cov.underlying_coverage(
            mongo_db, settings, "MIDCAP",
            window_from=date(2026, 1, 1), window_to=date(2026, 1, 2),
        )


async def test_underlying_coverage_builds_radar_from_family_gaps(monkeypatch):
    """Weekly-Camarilla radar status must reflect the spot-OR-levels union, not either alone."""
    day = date(2026, 1, 6)  # Tuesday, a trading day

    class _FakeSettings:
        NSE_HOLIDAYS_JSON = "does-not-matter.json"
        WAREHOUSE_STRIKE_BAND = 10
        MONGO_URI = "mongodb://unused"
        MONGO_DB_NAME = "unused"

    monkeypatch.setattr(cov, "holidays", lambda _path: set())
    monkeypatch.setattr(cov, "trading_days", lambda _from, _to, _hol: [day])

    async def _fake_options_family(settings, underlying, days, sync_client):
        return cov._empty_family(len(days)), set()

    monkeypatch.setattr(cov, "_options_family", _fake_options_family)

    # spot present, levels_weekly missing -> weekly Camarilla still "ready" (OR semantics).
    mongo_db = _FakeMongoDb(
        market_bars=_FakeCollection(
            agg_rows=[{"_id": datetime(day.year, day.month, day.day), "n": 375}],
            docs=[{"ts": _ist_ts(day)}],
        ),
        index_levels=_FakeCollection(docs=[]),
        option_bars=_FakeCollection(agg_rows=[]),
    )

    result = await cov.underlying_coverage(
        mongo_db, _FakeSettings(), "NIFTY", window_from=day, window_to=day,
        sync_client=object(),  # keeps the test offline — no real MongoClient() construction
    )

    assert result["radar"]["2026-01-06"]["spot"] == "ready"
    assert result["radar"]["2026-01-06"]["levels_weekly"] == "ready"
