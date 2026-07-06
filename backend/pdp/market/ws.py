from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.market.models import Tick

log = structlog.get_logger()

_CLIENT_QUEUE_SIZE = 50

ws_router = APIRouter(tags=["market-ws"])


class _Client:
    """One connected WebSocket consumer."""

    __slots__ = ("addr", "queue", "security_ids", "timeframes", "ws")

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        self.security_ids: set[str] = set()
        self.timeframes: set[str] = set()
        self.addr = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"

    def push(self, payload: str) -> None:
        """Non-blocking push; drop oldest if full."""
        if self.queue.full():
            try:
                self.queue.get_nowait()
                log.warning("ws_client_lagging", addr=self.addr)
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class WSHub:
    """
    Manages all connected /ws/market clients.

    publish_tick() and publish_bar() are called synchronously from TickRouter
    (no awaits — just queue puts).
    """

    def __init__(self) -> None:
        self._clients: set[_Client] = set()
        self._dirty_ticks: dict[str, Tick] = {}
        self._needs_broadcast: bool = False
        self._stop_event = asyncio.Event()

    async def run_broadcast_loop(self) -> None:
        """Broadcast latest ticks every 100ms to debounce high-frequency updates."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            if self._stop_event.is_set():
                break
            self.flush()

    def flush(self) -> None:
        """Flush batched ticks to connected clients."""
        if not self._needs_broadcast:
            return
        self._needs_broadcast = False
        dirty = self._dirty_ticks
        self._dirty_ticks = {}
        if not self._clients or not dirty:
            return

        now = time.time()
        for tick in dirty.values():
            payload = json.dumps(
                {
                    "type": "tick",
                    "security_id": tick.security_id,
                    "ltp": str(tick.ltp),
                    "ltt": tick.ltt.isoformat(),
                    "volume": tick.volume,
                    "ts": now,
                }
            )
            for client in self._clients:
                if tick.security_id in client.security_ids:
                    client.push(payload)

    def stop(self) -> None:
        """Signal the broadcast loop to stop."""
        self._stop_event.set()

    def _add(self, client: _Client) -> None:
        self._clients.add(client)
        log.info("ws_client_connected", addr=client.addr, total=len(self._clients))

    def _remove(self, client: _Client) -> None:
        self._clients.discard(client)
        log.info("ws_client_disconnected", addr=client.addr, total=len(self._clients))

    def publish_tick(self, tick: Tick) -> None:
        if not self._clients:
            return
        self._dirty_ticks[tick.security_id] = tick
        self._needs_broadcast = True

    def publish_bar(self, bar: BarClosed) -> None:
        if not self._clients:
            return
        payload = json.dumps(
            {
                "type": "bar",
                "security_id": bar.security_id,
                "timeframe": bar.timeframe,
                "bar_time": bar.bar_time.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": bar.volume,
                "oi": bar.oi,
                "ts": time.time(),
            }
        )
        for client in self._clients:
            if bar.security_id in client.security_ids and bar.timeframe in client.timeframes:
                client.push(payload)

    async def _pump(self, client: _Client) -> None:
        """Drain a client's queue to the WebSocket."""
        while True:
            msg = await client.queue.get()
            await client.ws.send_text(msg)

    async def handle(self, ws: WebSocket) -> None:
        """Entry point called by the FastAPI WS endpoint."""
        await ws.accept()
        client = _Client(ws)
        self._add(client)
        pump_task = asyncio.create_task(self._pump(client), name=f"ws-pump-{client.addr}")
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                action = msg.get("action")
                sids = {str(s) for s in msg.get("security_ids", [])}
                tfs = set(msg.get("timeframes", []))
                if action == "subscribe":
                    client.security_ids |= sids
                    client.timeframes |= tfs
                elif action == "unsubscribe":
                    client.security_ids -= sids
                    client.timeframes -= tfs
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("ws_client_error", addr=client.addr, exc=str(exc))
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
            self._remove(client)


@ws_router.websocket("/ws/market")
async def market_ws(ws: WebSocket) -> None:
    hub: WSHub = ws.app.state.ws_hub
    await hub.handle(ws)
