"""MongoDB persistence + history reads for events."""
from __future__ import annotations

from typing import Any

import structlog

from pdp.events.models import Event

log = structlog.get_logger()


class EventStore:
    """Thin async wrapper over the MongoDB ``events`` collection."""

    def __init__(self, mongo_db: Any = None) -> None:
        self._col: Any = mongo_db["events"] if mongo_db is not None else None

    async def insert(self, event: Event) -> None:
        if self._col is None:
            return
        try:
            await self._col.insert_one(event.to_mongo())
        except Exception as exc:  # never let persistence break delivery
            log.warning("event_store_insert_failed", event_type=event.event_type.value, exc=str(exc))

    async def list_events(
        self,
        *,
        security_id: str | None = None,
        event_type: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._col is None:
            return []
        query: dict[str, Any] = {}
        if security_id:
            query["security_id"] = security_id
        if event_type:
            query["event_type"] = event_type
        if severity:
            query["severity"] = severity
        cursor = self._col.find(query, sort=[("ts", -1)], limit=max(1, min(limit, 500)))
        out: list[dict[str, Any]] = []
        async for doc in cursor:
            doc.pop("_id", None)
            ts = doc.get("ts")
            if ts is not None and hasattr(ts, "isoformat"):
                doc["ts"] = ts.isoformat()
            out.append(doc)
        return out
