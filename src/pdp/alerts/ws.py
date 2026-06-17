from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pdp.alerts import service
from pdp.alerts.evaluator import AlertNotification

log = structlog.get_logger()

alerts_ws_router = APIRouter(tags=["alerts-ws"])
_CLIENT_QUEUE_SIZE = 100


class _Client:
    __slots__ = ("addr", "queue", "user_id", "ws")

    def __init__(self, ws: WebSocket, user_id: str) -> None:
        self.ws = ws
        self.user_id = user_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        self.addr = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"

    def push(self, payload: str) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class AlertsHub:
    """Broadcasts alert notifications to connected /ws/alerts clients."""

    def __init__(self) -> None:
        self._clients: dict[str, set[_Client]] = {}  # user_id -> set of clients

    def publish(self, user_id: str, notification: AlertNotification) -> None:
        """Publish alert notification to user's connected clients."""
        clients = self._clients.get(user_id, set())
        if not clients:
            return

        msg = json.dumps(notification.to_dict())
        for client in clients:
            client.push(msg)

    async def backfill_state(self, ws: WebSocket, user_id: str, alerts: list[Any]) -> None:
        """Send current alert state to newly connected client."""
        for alert in alerts:
            payload = {
                "id": alert.id,
                "security_id": alert.security_id,
                "condition": alert.condition,
                "threshold": str(alert.threshold),
                "status": alert.status,
                "channels": alert.channels,
                "created_at": alert.created_at.isoformat(),
            }
            await ws.send_text(json.dumps(payload))

    async def _pump(self, client: _Client) -> None:
        while True:
            msg = await client.queue.get()
            try:
                await client.ws.send_text(msg)
            except Exception as exc:
                log.warning("alert_ws_send_error", addr=client.addr, exc=str(exc))
                break

    async def handle(self, ws: WebSocket, user_id: str) -> None:
        await ws.accept()
        client = _Client(ws, user_id)

        if user_id not in self._clients:
            self._clients[user_id] = set()
        self._clients[user_id].add(client)
        log.info("alerts_ws_connected", user_id=user_id, addr=client.addr, total=len(self._clients[user_id]))

        pump = asyncio.create_task(self._pump(client), name=f"alerts-pump-{client.addr}")
        try:
            while True:
                await ws.receive_text()  # keep-alive; ignore client messages
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("alerts_ws_error", user_id=user_id, addr=client.addr, exc=str(exc))
        finally:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
            self._clients[user_id].discard(client)
            if not self._clients[user_id]:
                del self._clients[user_id]
            log.info("alerts_ws_disconnected", user_id=user_id, addr=client.addr)


@alerts_ws_router.websocket("/ws/alerts")
async def alerts_ws(ws: WebSocket) -> None:
    # Extract user_id from query parameter or header (TODO: validate JWT)
    query_token = ws.query_params.get("token")
    auth_header = ws.headers.get("Authorization", "")

    if not query_token and not auth_header.startswith("Bearer "):
        # No valid auth found
        await ws.close(code=4001, reason="Unauthorized: missing token")
        return

    # For v1, use placeholder user_id; actual JWT validation deferred
    user_id = "user_123"  # TODO: Extract from token

    hub: AlertsHub = ws.app.state.alerts_hub

    # Load and backfill current alert state
    from pdp.db.session import get_session_maker

    async with get_session_maker()() as db:
        alerts = await service.list_alerts(db, user_id)
        await hub.backfill_state(ws, user_id, alerts)

    await hub.handle(ws, user_id)
