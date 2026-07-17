"""EventStore.list_events: offset/pagination — regression for the /api/v1/events 500.

`routes.py::list_events` has always called `store.list_events(..., offset=pagination.offset)`,
but the store's signature had no `offset` parameter, so any request (including the default
`offset=0` from `PaginationParams`) raised `TypeError: list_events() got an unexpected keyword
argument 'offset'`, surfaced to the client as a 500.
"""
from __future__ import annotations

import pytest

from pdp.events.store import EventStore


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def __aiter__(self):
        for doc in self._docs:
            yield doc


class _FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.last_call: dict | None = None

    def find(self, query, *, sort=None, limit=None, skip=None):
        self.last_call = {"query": query, "sort": sort, "limit": limit, "skip": skip}
        # Mimic Mongo's skip/limit semantics for the fake in-memory doc list.
        start = skip or 0
        end = start + (limit or len(self._docs))
        return _FakeCursor(self._docs[start:end])


@pytest.mark.asyncio
async def test_list_events_accepts_offset_kwarg() -> None:
    """The exact call shape routes.py uses must not raise TypeError."""
    docs = [{"event_type": f"e{i}", "ts": None} for i in range(5)]
    col = _FakeCollection(docs)
    store = EventStore(mongo_db={"events": col})

    out = await store.list_events(limit=2, offset=2)

    assert col.last_call == {"query": {}, "sort": [("ts", -1)], "limit": 2, "skip": 2}
    assert [d["event_type"] for d in out] == ["e2", "e3"]


@pytest.mark.asyncio
async def test_list_events_defaults_offset_to_zero() -> None:
    docs = [{"event_type": f"e{i}", "ts": None} for i in range(3)]
    col = _FakeCollection(docs)
    store = EventStore(mongo_db={"events": col})

    out = await store.list_events(limit=10)

    assert col.last_call["skip"] == 0
    assert len(out) == 3


@pytest.mark.asyncio
async def test_list_events_no_collection_returns_empty() -> None:
    store = EventStore(mongo_db=None)
    assert await store.list_events(offset=5) == []
