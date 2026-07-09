"""UI / external log ingest endpoint — feeds the same pipeline with `source=ui`.

The Flutter `LogShipper` batches app logs and POSTs them here, fire-and-forget. Records are
enqueued to `pdp-logs-*` through the active indexer. Validation is via Pydantic so a
malformed batch yields 422 without enqueuing anything.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pdp.observability.indexer import get_active_indexer
from pdp.observability.schemas import IngestResponseOut

router = APIRouter(prefix="/api/v1/logs", tags=["observability"])


class UILogRecord(BaseModel):
    level: str = "info"
    event: str
    screen: str | None = None
    build: str | None = None
    device: str | None = None
    ts: str | None = None
    context: dict | None = None


class UILogBatch(BaseModel):
    records: list[UILogRecord] = Field(..., min_length=1)


@router.post("/ingest", response_model=IngestResponseOut, status_code=202)
async def ingest_logs(batch: UILogBatch) -> IngestResponseOut:
    indexer = get_active_indexer()
    accepted = 0
    for rec in batch.records:
        doc = {
            "@timestamp": rec.ts or datetime.now(UTC).isoformat(),
            "source": "ui",
            "level": rec.level.lower(),
            "event": rec.event,
            "screen": rec.screen,
            "build": rec.build,
            "device": rec.device,
            "context": rec.context,
        }
        if indexer is not None:
            indexer.enqueue("logs", doc)
        accepted += 1
    return IngestResponseOut(accepted=accepted)
