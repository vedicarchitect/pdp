"""WebSocket fan-out hub for live events (/ws/events)."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from pdp.events.models import Event
    from pdp.events.store import EventStore

log = structlog.get_logger()

_CLIENT_QUEUE_SIZE = 200
_BACKFILL_SIZE = 50


class _Client:
    __slots__ = ("addr", "queue", "ws")

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
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


class EventsHub:
    """Broadcasts events to all connected /ws/events clients (never blocks the publisher)."""

    def __init__(self, store: EventStore | None = None) -> None:
        self._clients: set[_Client] = set()
        self._recent: deque[str] = deque(maxlen=_BACKFILL_SIZE)
        self._store: Any = store  # optional EventStore for durable backfill

    def publish(self, event: Event) -> None:
        msg = json.dumps(event.to_dict())
        self._recent.append(msg)
        for client in self._clients:
            client.push(msg)

    async def _pump(self, client: _Client) -> None:
        while True:
            msg = await client.queue.get()
            try:
                await client.ws.send_text(msg)
            except Exception as exc:
                log.warning("events_ws_send_error", addr=client.addr, exc=str(exc))
                break

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(ws)
        self._clients.add(client)
        log.info("events_ws_connected", addr=client.addr, total=len(self._clients))

        # Backfill: prefer EventStore (survives restarts) then fall back to in-memory deque.
        backfill: list[str] = []
        if self._store is not None:
            try:
                docs = await self._store.list_events(limit=_BACKFILL_SIZE)
                backfill = [json.dumps(d) for d in reversed(docs)]  # oldest first
            except Exception as exc:
                log.warning("events_ws_backfill_error", exc=str(exc))
        if not backfill:
            backfill = list(self._recent)
        for msg in backfill:
            try:
                await ws.send_text(msg)
            except Exception:
                break

        pump = asyncio.create_task(self._pump(client), name=f"events-pump-{client.addr}")
        try:
            while True:
                await ws.receive_text()  # keep-alive; ignore client messages
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("events_ws_error", addr=client.addr, exc=str(exc))
        finally:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
            self._clients.discard(client)
            log.info("events_ws_disconnected", addr=client.addr)
