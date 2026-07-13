"""Test event persistence to Mongo."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.events.writer import EventWriter


@pytest.mark.asyncio
async def test_event_writer_batching_and_flush() -> None:
    fake_col = AsyncMock()
    # Return immediately to simulate no awaited round trip in enqueue
    writer = EventWriter(fake_col)
    
    # Enqueue a doc
    writer.enqueue({"event_type": "leg_open", "strategy_id": "test", "ts": "dummy"})
    
    # Assert nothing written yet (batching)
    fake_col.insert_many.assert_not_called()
    assert len(writer._buffer) == 1
    
    # Start and stop to force a flush
    await writer.start()
    await writer.stop()
    
    # Assert flush happened
    fake_col.insert_many.assert_called_once()
    args, kwargs = fake_col.insert_many.call_args
    batch = args[0]
    assert len(batch) == 1
    assert batch[0]["event_type"] == "leg_open"
