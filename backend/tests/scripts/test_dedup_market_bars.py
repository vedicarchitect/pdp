"""Tests for scripts/oneoff/dedup_market_bars.py (market-bars-duplicate-write-fix, group 3).

Uses an in-memory async stub for the market_bars collection (same pattern as
tests/scripts/test_rebuild_market_bars.py) so these run offline and never touch
production data.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "oneoff"))

from dedup_market_bars import _pick_survivor, dedup_one, find_duplicate_buckets  # noqa: E402


class _AsyncFindResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def to_list(self, length=None):
        return list(self._rows)


class _AsyncAggCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for row in self._rows:
            yield row


class _FakeBarsCollection:
    """Stub for market_bars supporting exactly what dedup_market_bars.py calls."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = list(docs)
        self._next_id = 1000

    def _exact_match(self, query: dict, doc: dict) -> bool:
        return (
            doc["metadata"]["security_id"] == query["metadata.security_id"]
            and doc["metadata"]["timeframe"] == query["metadata.timeframe"]
            and doc["ts"] == query["ts"]
        )

    def find(self, query: dict):
        return _AsyncFindResult([d for d in self._docs if self._exact_match(query, d)])

    async def delete_many(self, query: dict) -> None:
        self._docs = [d for d in self._docs if not self._exact_match(query, d)]

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(doc)

    def aggregate(self, pipeline: list[dict]):
        # Minimal re-implementation of the group-by-bucket + count>1 filter for tests —
        # exercises the same logic the real Mongo aggregation pipeline performs.
        buckets: dict[tuple, list[dict]] = {}
        for doc in self._docs:
            key = (doc["metadata"]["security_id"], doc["metadata"]["timeframe"], doc["ts"])
            buckets.setdefault(key, []).append(doc)
        rows = [
            {"_id": {"sid": k[0], "tf": k[1], "ts": k[2]}, "count": len(v)}
            for k, v in buckets.items()
            if len(v) > 1
        ]
        return _AsyncAggCursor(rows)


def _doc(sid: str, tf: str, iso: str, volume: int, doc_id: str) -> dict:
    return {
        "_id": doc_id,
        "ts": datetime.fromisoformat(iso).replace(tzinfo=UTC),
        "metadata": {"security_id": sid, "timeframe": tf},
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 103.0,
        "volume": volume,
        "oi": 0,
    }


def test_pick_survivor_keeps_highest_volume():
    docs = [
        _doc("13", "1D", "2026-01-06T18:30:00", volume=100, doc_id="a"),
        _doc("13", "1D", "2026-01-06T18:30:00", volume=900, doc_id="b"),  # fragment vs full bar
        _doc("13", "1D", "2026-01-06T18:30:00", volume=50, doc_id="c"),
    ]
    survivor = _pick_survivor(docs)
    assert survivor["_id"] == "b"


def test_pick_survivor_ties_broken_by_id():
    docs = [
        _doc("13", "1D", "2026-01-06T18:30:00", volume=500, doc_id="a"),
        _doc("13", "1D", "2026-01-06T18:30:00", volume=500, doc_id="b"),
    ]
    survivor = _pick_survivor(docs)
    assert survivor["_id"] == "b"  # larger _id wins the tie


@pytest.mark.asyncio
async def test_find_duplicate_buckets_only_returns_buckets_with_more_than_one_doc():
    col = _FakeBarsCollection(
        [
            _doc("13", "1D", "2026-01-06T18:30:00", volume=100, doc_id="a"),
            _doc("13", "1D", "2026-01-06T18:30:00", volume=900, doc_id="b"),
            _doc("25", "1D", "2026-01-06T18:30:00", volume=500, doc_id="c"),  # unique, not a dup
        ]
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)
    buckets = await find_duplicate_buckets(col, start, end)
    assert len(buckets) == 1
    assert buckets[0]["_id"]["sid"] == "13"
    assert buckets[0]["count"] == 2


@pytest.mark.asyncio
async def test_dedup_one_dry_run_makes_no_writes(tmp_path):
    ts = datetime(2026, 1, 6, 18, 30, tzinfo=UTC)
    docs = [
        _doc("13", "1D", "2026-01-06T18:30:00", volume=100, doc_id="a"),
        _doc("13", "1D", "2026-01-06T18:30:00", volume=900, doc_id="b"),
    ]
    col = _FakeBarsCollection(docs)
    summary = await dedup_one(col, "13", "1D", ts, tmp_path / "backup.jsonl", dry_run=True)
    assert summary["duplicate_count"] == 2
    assert summary["removed_count"] == 1
    assert len(col._docs) == 2  # nothing actually deleted


@pytest.mark.asyncio
async def test_dedup_one_real_run_leaves_exactly_one_survivor(tmp_path):
    ts = datetime(2026, 1, 6, 18, 30, tzinfo=UTC)
    docs = [
        _doc("13", "1D", "2026-01-06T18:30:00", volume=100, doc_id="a"),
        _doc("13", "1D", "2026-01-06T18:30:00", volume=900, doc_id="b"),
        _doc("13", "1D", "2026-01-06T18:30:00", volume=50, doc_id="c"),
    ]
    col = _FakeBarsCollection(docs)
    backup_path = tmp_path / "backup.jsonl"
    summary = await dedup_one(col, "13", "1D", ts, backup_path, dry_run=False)

    assert summary["removed_count"] == 2
    assert len(col._docs) == 1
    assert col._docs[0]["_id"] == "b"  # highest volume survived
    assert backup_path.exists()
    backed_up = backup_path.read_text().strip().splitlines()
    assert len(backed_up) == 3  # every duplicate document backed up before delete
