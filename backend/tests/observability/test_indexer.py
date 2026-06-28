"""Indexer: non-blocking enqueue, drop-on-full, bulk flush, OS-down no-op."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pdp.observability.indexer import OpenSearchIndexer, _month_suffix


def test_enqueue_resolves_monthly_index_and_id():
    idx = OpenSearchIndexer(client=AsyncMock(), prefix="pdp", queue_max=10)
    idx.enqueue("logs", {"@timestamp": "2026-06-28T10:00:00+05:30", "event": "x"}, doc_id="d1")
    action = idx._queue.get_nowait()
    assert action["_index"] == "pdp-logs-2026.06"
    assert action["_id"] == "d1"
    assert action["_source"]["event"] == "x"


def test_enqueue_never_blocks_and_drops_on_full():
    idx = OpenSearchIndexer(client=AsyncMock(), prefix="pdp", queue_max=2)
    for n in range(5):
        idx.enqueue("logs", {"@timestamp": "2026-06-28T00:00:00Z", "n": n})
    assert idx.dropped == 3  # only 2 fit
    assert idx._queue.qsize() == 2


@pytest.mark.asyncio
async def test_flush_bulk_indexes(monkeypatch):
    captured = {}

    async def fake_bulk(client, actions, raise_on_error=False):  # noqa: ANN001
        captured["actions"] = list(actions)
        return (len(captured["actions"]), [])

    monkeypatch.setattr("opensearchpy.helpers.async_bulk", fake_bulk)
    idx = OpenSearchIndexer(client=AsyncMock(), prefix="pdp")
    idx.enqueue("logs", {"@timestamp": "2026-06-28T00:00:00Z", "event": "a"})
    await idx._flush()
    assert len(captured["actions"]) == 1


@pytest.mark.asyncio
async def test_flush_swallows_opensearch_errors(monkeypatch):
    async def boom(client, actions, raise_on_error=False):  # noqa: ANN001
        raise ConnectionError("opensearch down")

    monkeypatch.setattr("opensearchpy.helpers.async_bulk", boom)
    idx = OpenSearchIndexer(client=AsyncMock(), prefix="pdp")
    idx.enqueue("logs", {"@timestamp": "2026-06-28T00:00:00Z", "event": "a"})
    # Must not raise — OS down can never break the app.
    await idx._flush()
    assert idx._warned is True


def test_month_suffix_fallback_for_bad_ts():
    assert _month_suffix("2026-06-28T10:00:00+05:30") == "2026.06"
    # bad input falls back to a current-month string of the right shape
    assert len(_month_suffix("garbage")) == 7
