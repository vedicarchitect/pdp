from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

    from pdp.market.bars import BarClosed

log = structlog.get_logger()

_FLUSH_INTERVAL = 1.0  # seconds
_FLUSH_BATCH = 500  # documents
_MAX_BUFFER = 10_000  # drop-oldest threshold


class BarWriter:
    """
    Batched motor writer for the market_bars MongoDB time-series collection.

    Call enqueue() from the asyncio event loop (no locking needed — single-threaded).
    start() launches the background flush loop; stop() drains and exits.
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._col = collection
        self._buffer: deque[dict] = deque()
        self._stop_event = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop(), name="bar-writer-flush")
        log.info("bar_writer_started")

    async def stop(self, *, timeout_s: float = 10.0) -> None:
        self._stop_event.set()
        if self._flush_task is not None:
            # Bound the final drain: it issues one more delete_many+insert_many, and if
            # Mongo is pegged that await would otherwise block shutdown forever (the hang
            # that forced SIGKILL). wait_for cancels the drain on timeout and awaits the
            # cancellation, so exit proceeds rather than wedging.
            try:
                await asyncio.wait_for(self._flush_task, timeout=timeout_s)
            except TimeoutError:
                log.warning("bar_writer_stop_timeout", timeout_s=timeout_s, buffered=len(self._buffer))
            except Exception as exc:
                log.warning("bar_writer_stop_error", exc=str(exc))

    def enqueue(self, bar: BarClosed) -> None:
        if len(self._buffer) >= _MAX_BUFFER:
            self._buffer.popleft()
            log.warning("bar_writer_overflow", buffer_size=_MAX_BUFFER)
        self._buffer.append(
            {
                "ts": bar.bar_time,
                "metadata": {"security_id": bar.security_id, "timeframe": bar.timeframe},
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": bar.volume,
                "oi": bar.oi,
            }
        )

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

        raw_batch: list[dict] = []
        while self._buffer and len(raw_batch) < _FLUSH_BATCH:
            raw_batch.append(self._buffer.popleft())
        if not raw_batch:
            return
        # Dedup within this batch first (last write wins) — two enqueue() calls for the
        # same bucket before a flush must not both survive into insert_many.
        by_key: dict[tuple, dict] = {}
        for doc in raw_batch:
            key = (doc["metadata"]["security_id"], doc["metadata"]["timeframe"], doc["ts"])
            by_key[key] = doc
        batch = list(by_key.values())
        try:
            # Delete-then-insert per exact (security_id, timeframe, ts) bucket, mirroring
            # rebuild_market_bars.py — a timeseries collection can't carry a unique index, and
            # `insert_many` alone duplicates a bucket that's enqueued twice (a late tick can
            # reopen a builder BarSessionScheduler.flush_session() already force-closed, or a
            # process restart can re-aggregate an overlapping tick window). Idempotent: safe to
            # run even if this exact batch was already flushed once.
            dedup_query = {
                "$or": [
                    {
                        "ts": doc["ts"],
                        "metadata.security_id": doc["metadata"]["security_id"],
                        "metadata.timeframe": doc["metadata"]["timeframe"],
                    }
                    for doc in batch
                ]
            }
            await self._col.delete_many(dedup_query)
            await self._col.insert_many(batch, ordered=False)
            log.debug("bar_writer_flushed", rows=len(batch))
        except BulkWriteError as exc:
            details = exc.details
            n_errors = len(details.get("writeErrors", []))
            n_inserted = details.get("nInserted", 0)
            log.warning(
                "bar_writer_bulk_error",
                inserted=n_inserted,
                errors=n_errors,
            )
        except Exception as exc:
            log.warning("bar_writer_flush_error", exc=str(exc), rows=len(batch))
            for doc in reversed(batch):
                self._buffer.appendleft(doc)
