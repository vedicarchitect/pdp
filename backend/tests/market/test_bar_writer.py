"""Unit tests for BarWriter → motor collection integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.market.bar_writer import BarWriter
from pdp.market.bars import BarClosed


def _bar(
    sid: str = "13",
    tf: str = "5m",
    bar_time: str = "2026-01-02T03:45:00",
) -> BarClosed:
    return BarClosed(
        security_id=sid,
        timeframe=tf,
        bar_time=datetime.fromisoformat(bar_time).replace(tzinfo=UTC),
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("98.00"),
        close=Decimal("103.00"),
        volume=500,
        oi=0,
    )


@pytest.fixture
def mock_collection():
    col = MagicMock()
    col.insert_many = AsyncMock(return_value=MagicMock(inserted_ids=[]))
    col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    return col


@pytest.mark.asyncio
async def test_enqueue_and_flush_inserts_correct_document(mock_collection):
    writer = BarWriter(mock_collection)
    bar = _bar()
    writer.enqueue(bar)

    await writer._flush()

    mock_collection.insert_many.assert_called_once()
    docs = mock_collection.insert_many.call_args[0][0]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["ts"] == bar.bar_time
    assert doc["metadata"] == {"security_id": "13", "timeframe": "5m"}
    assert doc["open"] == float(bar.open)
    assert doc["high"] == float(bar.high)
    assert doc["low"] == float(bar.low)
    assert doc["close"] == float(bar.close)
    assert doc["volume"] == 500
    assert doc["oi"] == 0


@pytest.mark.asyncio
async def test_flush_empty_buffer_does_not_call_insert(mock_collection):
    writer = BarWriter(mock_collection)
    await writer._flush()
    mock_collection.insert_many.assert_not_called()


@pytest.mark.asyncio
async def test_overflow_drops_oldest(mock_collection):
    writer = BarWriter(mock_collection)
    # Fill buffer to limit + 1
    for i in range(10_001):
        writer.enqueue(_bar(sid=str(i)))
    assert len(writer._buffer) == 10_000
    # The first enqueued bar (sid="0") should have been dropped
    sids = [doc["metadata"]["security_id"] for doc in writer._buffer]
    assert "0" not in sids


@pytest.mark.asyncio
async def test_bulk_write_error_logged_not_requeued(mock_collection):
    from pymongo.errors import BulkWriteError

    mock_collection.insert_many = AsyncMock(
        side_effect=BulkWriteError({"nInserted": 0, "writeErrors": [{"code": 11000}]})
    )
    writer = BarWriter(mock_collection)
    writer.enqueue(_bar())

    # Should not raise, should not re-queue
    await writer._flush()
    assert len(writer._buffer) == 0


@pytest.mark.asyncio
async def test_generic_error_requeues_batch(mock_collection):
    mock_collection.insert_many = AsyncMock(side_effect=Exception("network timeout"))
    writer = BarWriter(mock_collection)
    writer.enqueue(_bar())

    await writer._flush()
    # Batch is put back at the front of the buffer for retry
    assert len(writer._buffer) == 1


# ---------------------------------------------------------------------------
# market-bars-duplicate-write-fix: idempotent flush (delete-then-insert per
# exact (security_id, timeframe, ts) bucket)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_deletes_before_inserting_each_bucket(mock_collection):
    """Every flush deletes any pre-existing document for the buckets it's about to
    write, so a bucket enqueued twice across two separate flushes (e.g. a late tick
    reopening a builder BarSessionScheduler.flush_session() already force-closed)
    never leaves two documents in Mongo."""
    writer = BarWriter(mock_collection)
    bar = _bar()

    writer.enqueue(bar)
    await writer._flush()

    writer.enqueue(bar)  # same (sid, tf, bar_time) bucket, re-enqueued
    await writer._flush()

    assert mock_collection.delete_many.call_count == 2
    delete_query = mock_collection.delete_many.call_args[0][0]
    assert delete_query == {
        "$or": [
            {
                "ts": bar.bar_time,
                "metadata.security_id": "13",
                "metadata.timeframe": "5m",
            }
        ]
    }
    assert mock_collection.insert_many.call_count == 2


@pytest.mark.asyncio
async def test_duplicate_bucket_within_same_batch_is_deduped_before_insert(mock_collection):
    """Two enqueue() calls for the identical bucket landing in the same flush batch
    (e.g. an in-process retry) must not both survive into insert_many — last write
    wins, and only one document per bucket is ever sent to Mongo."""
    writer = BarWriter(mock_collection)
    bar = _bar()

    writer.enqueue(bar)
    writer.enqueue(bar)  # duplicate, same batch
    await writer._flush()

    docs = mock_collection.insert_many.call_args[0][0]
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_distinct_buckets_in_one_batch_all_survive(mock_collection):
    """Dedup is scoped to the exact (sid, tf, ts) key — distinct buckets in the same
    batch are unaffected."""
    writer = BarWriter(mock_collection)
    writer.enqueue(_bar(sid="13"))
    writer.enqueue(_bar(sid="25"))
    writer.enqueue(_bar(bar_time="2026-01-02T03:50:00"))

    await writer._flush()

    docs = mock_collection.insert_many.call_args[0][0]
    assert len(docs) == 3


@pytest.mark.asyncio
async def test_stop_times_out_on_wedged_flush_instead_of_hanging(mock_collection):
    """A final drain that blocks on a pegged Mongo must not wedge shutdown. stop() bounds
    the drain and returns within its timeout by cancelling it, rather than awaiting forever
    (the hang that previously forced SIGKILL during the CPU-spike incident)."""
    import asyncio

    started = asyncio.Event()

    async def _never_returns(*_a, **_k):
        started.set()
        await asyncio.sleep(3600)

    mock_collection.delete_many = AsyncMock(side_effect=_never_returns)

    writer = BarWriter(mock_collection)
    await writer.start()
    writer.enqueue(_bar())
    # Let the background flush loop pick up the bar and block inside delete_many.
    await asyncio.wait_for(started.wait(), timeout=2)

    # The outer wait_for is the assertion: if stop() did not bound its drain it would hang
    # here and raise TimeoutError. With the guard it returns in ~0.2s.
    await asyncio.wait_for(writer.stop(timeout_s=0.2), timeout=2)
