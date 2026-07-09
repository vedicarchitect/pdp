"""Read REST: unified log search + bar-anchored strangle session narrative.

`GET /api/v1/observability/logs` — search `pdp-logs-*` (filter by source/level/text).
`GET /api/v1/analysis/session` — Claude-ready session narrative for a date (404 when empty).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from pdp.observability.client import get_opensearch
from pdp.observability.query import (
    build_session,
    fetch_session_events,
    search_logs,
)
from pdp.observability.schemas import LogsResponseOut, SessionResponseOut

router = APIRouter(tags=["observability"])

_DEFAULT_STRATEGY = "directional_strangle"


@router.get("/api/v1/observability/logs", response_model=LogsResponseOut)
async def get_logs(
    source: str | None = None,
    level: str | None = None,
    q: str | None = None,
    size: int = Query(100, ge=1, le=1000),
) -> LogsResponseOut:
    client = get_opensearch()
    if client is None:
        raise HTTPException(status_code=503, detail="OpenSearch disabled")
    hits = await search_logs(client, source=source, level=level, query=q, size=size)
    return LogsResponseOut(count=len(hits), logs=hits)


@router.get("/api/v1/analysis/session", response_model=SessionResponseOut)
async def get_session(
    date: str,
    strategy_id: str = _DEFAULT_STRATEGY,
) -> SessionResponseOut:
    client = get_opensearch()
    if client is None:
        raise HTTPException(status_code=503, detail="OpenSearch disabled")
    events = await fetch_session_events(client, date=date, strategy_id=strategy_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"no session events for {date}")
    res = build_session(events, date=date, strategy_id=strategy_id)
    return SessionResponseOut(**res)
