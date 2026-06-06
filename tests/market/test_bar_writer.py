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
