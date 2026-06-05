from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed

log = structlog.get_logger()

_FLUSH_INTERVAL = 1.0  # seconds
_FLUSH_BATCH = 500     # rows
_MAX_BUFFER = 10_000   # drop-oldest threshold

# Columns must match market_bars table exactly
_COLUMNS = ("security_id", "timeframe", "bar_time", "open", "high", "low", "close", "volume", "oi")


class BarWriter:
    """
    Batched asyncpg COPY writer for the market_bars hypertable.

    Call enqueue() from the asyncio event loop (no locking needed — single-threaded).
    start() launches the background flush loop; stop() drains and exits.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn  # raw asyncpg DSN (not SQLAlchemy URL)
        self._buffer: deque[tuple] = deque()
        self._stop_event = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop(), name="bar-writer-flush")
        log.info("bar_writer_started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._flush_task is not None:
            await self._flush_task

    def enqueue(self, bar: BarClosed) -> None:
        """Add a closed bar to the write buffer. Drop oldest if buffer overflows."""
        if len(self._buffer) >= _MAX_BUFFER:
            self._buffer.popleft()
            log.warning("bar_writer_overflow", buffer_size=_MAX_BUFFER)
        self._buffer.append(
            (
                bar.security_id,
                bar.timeframe,
                bar.bar_time,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.oi,
            )
        )

    async def _flush_loop(self) -> None:
        import asyncpg

        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(self._dsn)
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=_FLUSH_INTERVAL
                    )
                except TimeoutError:
                    pass
                if self._buffer:
                    await self._flush(conn)
            # Final drain on shutdown
            if self._buffer and conn is not None:
                await self._flush(conn)
        except Exception as exc:
            log.error("bar_writer_fatal", exc=str(exc))
        finally:
            if conn is not None:
                await conn.close()

    async def _flush(self, conn) -> None:  # type: ignore[no-untyped-def]
        import asyncpg

        batch: list[tuple] = []
        while self._buffer and len(batch) < _FLUSH_BATCH:
            batch.append(self._buffer.popleft())
        if not batch:
            return
        try:
            await conn.copy_records_to_table(
                "market_bars",
                records=batch,
                columns=list(_COLUMNS),
            )
            log.debug("bar_writer_flushed", rows=len(batch))
        except asyncpg.exceptions.UniqueViolationError:
            # Duplicate bar_time (replay / reconnect) — silently skip
            log.debug("bar_writer_duplicate_skipped", rows=len(batch))
        except Exception as exc:
            log.warning("bar_writer_flush_error", exc=str(exc), rows=len(batch))
            # Re-queue the batch at the front so it retries next flush
            for row in reversed(batch):
                self._buffer.appendleft(row)
