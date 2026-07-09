from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger()

orders_ws_router = APIRouter(tags=["orders-ws"])
_CLIENT_QUEUE_SIZE = 100


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


class OrdersHub:
    """Broadcasts order/trade/position events to all connected /ws/orders clients."""

    def __init__(self, redis: Any | None = None) -> None:
        self._clients: set[_Client] = set()
        self._position_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._fill_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._redis = redis

    def register_position_callback(self, cb: Callable[[dict[str, Any]], None]) -> None:
        self._position_callbacks.append(cb)

    def register_fill_callback(self, cb: Callable[[dict[str, Any]], None]) -> None:
        self._fill_callbacks.append(cb)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "position":
            for cb in self._position_callbacks:
                try:
                    cb(payload)
                except Exception as exc:
                    log.warning("position_callback_error", exc=str(exc))
        if event_type == "trade":
            for cb in self._fill_callbacks:
                try:
                    cb(payload)
                except Exception as exc:
                    log.warning("fill_callback_error", exc=str(exc))
                    
        msg = json.dumps({"type": event_type, "payload": payload})
        if self._redis is not None:
            asyncio.create_task(self._redis.publish(f"orders.{event_type}", msg))

        if not self._clients:
            return
        for client in self._clients:
            client.push(msg)

    def publish_raw(self, msg: str) -> None:
        if not self._clients:
            return
        for client in self._clients:
            client.push(msg)

    async def _pump(self, client: _Client) -> None:
        while True:
            msg = await client.queue.get()
            await client.ws.send_text(msg)

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(ws)
        self._clients.add(client)
        log.info("orders_ws_connected", addr=client.addr, total=len(self._clients))
        pump = asyncio.create_task(self._pump(client), name=f"orders-pump-{client.addr}")
        try:
            while True:
                await ws.receive_text()  # keep-alive; ignore client messages
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("orders_ws_error", addr=client.addr, exc=str(exc))
        finally:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:
                pass
            self._clients.discard(client)
            log.info("orders_ws_disconnected", addr=client.addr, total=len(self._clients))


@orders_ws_router.websocket("/ws/orders")
async def orders_ws(ws: WebSocket) -> None:
    hub: OrdersHub = ws.app.state.orders_hub
    await hub.handle(ws)
