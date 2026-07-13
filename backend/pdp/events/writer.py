from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = structlog.get_logger()

_FLUSH_INTERVAL = 1.0  # seconds
_FLUSH_BATCH = 500  # documents
_MAX_BUFFER = 10_000  # drop-oldest threshold


class EventWriter:
    """
    Batched motor writer for the events MongoDB time-series collection.

    Call enqueue() from the asyncio event loop (no locking needed — single-threaded).
    start() launches the background flush loop; stop() drains and exits.
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._col = collection
        self._buffer: deque[dict[str, Any]] = deque()
        self._stop_event = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop(), name="event-writer-flush")
        log.info("event_writer_started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._flush_task is not None:
            await self._flush_task

    def enqueue(self, event_doc: dict[str, Any]) -> None:
        if len(self._buffer) >= _MAX_BUFFER:
            self._buffer.popleft()
            log.warning("event_writer_overflow", buffer_size=_MAX_BUFFER)
        # We expect event_doc to already be formatted correctly for MongoDB,
        # with 'ts' as a datetime object for the time-series TTL index.
        self._buffer.append(event_doc)

    async def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=_FLUSH_INTERVAL)
            except TimeoutError:
                pass
            if self._buffer:
                await self._flush()
        # Final drain on shutdown
        if self._buffer:
            await self._flush()

    async def _flush(self) -> None:
        from pymongo.errors import BulkWriteError

        batch: list[dict[str, Any]] = []
        while self._buffer and len(batch) < _FLUSH_BATCH:
            batch.append(self._buffer.popleft())
        if not batch:
            return
        try:
            await self._col.insert_many(batch, ordered=False)
            log.debug("event_writer_flushed", rows=len(batch))
        except BulkWriteError as exc:
            details = exc.details
            n_errors = len(details.get("writeErrors", []))
            n_inserted = details.get("nInserted", 0)
            log.warning(
                "event_writer_bulk_error",
                inserted=n_inserted,
                errors=n_errors,
            )
        except Exception as exc:
            log.warning("event_writer_flush_error", exc=str(exc), rows=len(batch))
            for doc in reversed(batch):
                self._buffer.appendleft(doc)
