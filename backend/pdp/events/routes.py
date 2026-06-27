"""REST + WebSocket endpoints for the live event publisher."""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel

from pdp.events.models import EventType

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/events", tags=["events"])
events_ws_router = APIRouter(tags=["events-ws"])

_ALL_EVENT_TYPES = [et.value for et in EventType]


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeBody(BaseModel):
    endpoint: str
    keys: PushKeys


class EventTypeConfigPatch(BaseModel):
    event_type: str
    push_enabled: bool


@router.get("")
async def list_events(
    request: Request,
    security_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    store = getattr(request.app.state, "event_store", None)
    if store is None:
        return {"events": [], "count": 0}
    events = await store.list_events(
        security_id=security_id, event_type=event_type, severity=severity, limit=limit
    )
    return {"events": events, "count": len(events)}


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    svc = getattr(request.app.state, "event_service", None)
    if svc is None:
        return {"enabled": False, "event_type_push": {et: True for et in _ALL_EVENT_TYPES}}
    c = svc.cfg
    event_type_push = {et: et not in c.push_disabled_types for et in _ALL_EVENT_TYPES}
    return {
        "enabled": c.enabled,
        "timeframes": c.timeframes,
        "ema_pairs": c.ema_pairs,
        "watch_levels": c.watch_levels,
        "otm_distance_pts": c.otm_distance_pts,
        "mtm_swing_inr": c.mtm_swing_inr,
        "push_enabled": c.push_enabled,
        "push_min_severity": c.push_min_severity,
        "event_type_push": event_type_push,
    }


@router.patch("/config")
async def patch_config(request: Request, body: EventTypeConfigPatch) -> dict[str, Any]:
    svc = getattr(request.app.state, "event_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="event_service unavailable")
    if body.event_type not in _ALL_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown event_type: {body.event_type}")
    if body.push_enabled:
        svc.cfg.push_disabled_types.discard(body.event_type)
    else:
        svc.cfg.push_disabled_types.add(body.event_type)
    return {"event_type": body.event_type, "push_enabled": body.push_enabled}


@router.get("/push/vapid-key")
async def vapid_key(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"public_key": settings.EVENTS_VAPID_PUBLIC_KEY}


@router.post("/push/subscribe")
async def push_subscribe(request: Request, body: PushSubscribeBody) -> dict[str, str]:
    sender = getattr(request.app.state, "web_push_sender", None)
    if sender is None:
        return {"status": "push_unavailable"}
    await sender.add_subscription(body.endpoint, body.keys.p256dh, body.keys.auth)
    return {"status": "subscribed"}


@events_ws_router.websocket("/ws/events")
async def events_ws(ws: WebSocket) -> None:
    hub = getattr(ws.app.state, "events_hub", None)
    if hub is None:
        await ws.close(code=1011, reason="events hub unavailable")
        return
    await hub.handle(ws)
