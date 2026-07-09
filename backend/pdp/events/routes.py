"""REST + WebSocket endpoints for the live event publisher."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel

from pdp.deps import PaginationParams
from pdp.events.models import EventType
from pdp.schemas import Page
from pdp.events.schemas import EventOut, EventConfigOut, EventTypeConfigPatchResponse, VapidKeyOut, StatusOut

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


@router.get("", response_model=Page[EventOut])
async def list_events(
    request: Request,
    security_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    pagination: PaginationParams = Depends(),
) -> Page[EventOut]:
    store = getattr(request.app.state, "event_store", None)
    if store is None:
        return Page(items=[], limit=pagination.limit, offset=pagination.offset)
    events = await store.list_events(
        security_id=security_id, event_type=event_type, severity=severity, limit=pagination.limit, offset=pagination.offset
    )
    items = [EventOut(**e) for e in events]
    return Page(items=items, limit=pagination.limit, offset=pagination.offset)


@router.get("/config", response_model=EventConfigOut)
async def get_config(request: Request) -> EventConfigOut:
    svc = getattr(request.app.state, "event_service", None)
    if svc is None:
        return EventConfigOut(enabled=False, event_type_push={et: True for et in _ALL_EVENT_TYPES})
    c = svc.cfg
    event_type_push = {et: et not in c.push_disabled_types for et in _ALL_EVENT_TYPES}
    return EventConfigOut(
        enabled=c.enabled,
        timeframes=c.timeframes,
        ema_pairs=c.ema_pairs,
        watch_levels=c.watch_levels,
        otm_distance_pts=c.otm_distance_pts,
        mtm_swing_inr=c.mtm_swing_inr,
        push_enabled=c.push_enabled,
        push_min_severity=c.push_min_severity,
        event_type_push=event_type_push,
    )


@router.patch(
    "/config",
    response_model=EventTypeConfigPatchResponse,
    status_code=200,
    summary="Update event type configuration",
    description="Enable or disable push notifications for a specific event type.",
)
async def patch_config(request: Request, body: EventTypeConfigPatch) -> EventTypeConfigPatchResponse:
    svc = getattr(request.app.state, "event_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="event_service unavailable")
    if body.event_type not in _ALL_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown event_type: {body.event_type}")
    if body.push_enabled:
        svc.cfg.push_disabled_types.discard(body.event_type)
    else:
        svc.cfg.push_disabled_types.add(body.event_type)
    return EventTypeConfigPatchResponse(event_type=body.event_type, push_enabled=body.push_enabled)


@router.get("/push/vapid-key", response_model=VapidKeyOut)
async def vapid_key(request: Request) -> VapidKeyOut:
    settings = request.app.state.settings
    return VapidKeyOut(public_key=settings.EVENTS_VAPID_PUBLIC_KEY)


@router.post(
    "/push/subscribe",
    response_model=StatusOut,
    status_code=201,
    summary="Subscribe to push notifications",
)
async def push_subscribe(request: Request, body: PushSubscribeBody) -> StatusOut:
    sender = getattr(request.app.state, "web_push_sender", None)
    if sender is None:
        return StatusOut(status="push_unavailable")
    await sender.add_subscription(body.endpoint, body.keys.p256dh, body.keys.auth)
    return StatusOut(status="subscribed")


@events_ws_router.websocket("/ws/events")
async def events_ws(ws: WebSocket) -> None:
    hub = getattr(ws.app.state, "events_hub", None)
    if hub is None:
        await ws.close(code=1011, reason="events hub unavailable")
        return
    await hub.handle(ws)
