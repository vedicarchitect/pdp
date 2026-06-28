"""The single sink to OpenSearch — a non-blocking, bulk-flushing indexer.

`enqueue()` never awaits and never blocks the caller (it is called from the structlog
processor on the hot path). When the queue is full, documents are dropped and counted. A
background loop flushes in bulk on an interval or when a batch threshold is reached. When
OpenSearch is unreachable, a single warning is logged and the batch is discarded — the API
and stdout logging continue unaffected (JSONL/Mongo remain the source of truth).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch

log = structlog.get_logger("pdp.observability").bind(_no_ship=True)

# Module-global active indexer: set by the app lifespan, read by the structlog processor and
# the typed sinks. ``None`` (tests / OpenSearch disabled) makes every enqueue a no-op.
_active: OpenSearchIndexer | None = None


def set_active_indexer(indexer: OpenSearchIndexer | None) -> None:
    global _active
    _active = indexer


def get_active_indexer() -> OpenSearchIndexer | None:
    return _active


class OpenSearchIndexer:
    def __init__(
        self,
        client: AsyncOpenSearch,
        *,
        prefix: str = "pdp",
        bulk_interval: float = 2.0,
        bulk_max: int = 500,
        queue_max: int = 10000,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._bulk_interval = bulk_interval
        self._bulk_max = bulk_max
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_max)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0
        self._warned = False

    # -- enqueue (hot path; sync, non-blocking) -------------------------------- #

    def enqueue(self, index_base: str, doc: dict[str, Any], doc_id: str | None = None) -> None:
        """Queue one document for bulk indexing. Never blocks; drops on a full queue.

        ``index_base`` is the family (e.g. ``"logs"``, ``"strangle-events"``); the full
        monthly index name is resolved here from the document timestamp.
        """
        ts = doc.get("@timestamp") or doc.get("timestamp")
        month = _month_suffix(ts)
        action: dict[str, Any] = {
            "_index": f"{self._prefix}-{index_base}-{month}",
            "_source": doc,
        }
        if doc_id is not None:
            action["_id"] = doc_id
        try:
            self._queue.put_nowait(action)
        except asyncio.QueueFull:
            self.dropped += 1

    # -- lifecycle ------------------------------------------------------------- #

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="opensearch-indexer")
        log.info("opensearch_indexer_started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self._flush()  # drain remaining
        if self.dropped:
            log.warning("opensearch_indexer_dropped", dropped=self.dropped)

    # -- flush loop ------------------------------------------------------------ #

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._bulk_interval)
            except TimeoutError:
                pass
            await self._flush()

    async def _drain(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while not self._queue.empty():
            batch.append(self._queue.get_nowait())
            if len(batch) >= self._bulk_max:
                break
        return batch

    async def _flush(self) -> None:
        batch = await self._drain()
        if not batch:
            return
        try:
            from opensearchpy.helpers import async_bulk

            await async_bulk(self._client, batch, raise_on_error=False)
            self._warned = False
        except Exception as exc:  # noqa: BLE001 — OS down must never break the app
            if not self._warned:
                log.warning("opensearch_bulk_failed", count=len(batch), exc=str(exc))
                self._warned = True


def _month_suffix(ts: Any) -> str:
    """Monthly index suffix (`YYYY.MM`) from an ISO timestamp, or current UTC month."""
    if isinstance(ts, str) and len(ts) >= 7:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y.%m")
        except ValueError:
            pass
    return datetime.now(UTC).strftime("%Y.%m")
