"""WebSocket hub for options chain snapshot broadcasts."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import structlog

log = structlog.get_logger()

_CLIENT_QUEUE_SIZE = 20


class _OptionsClient:
    __slots__ = ("addr", "expiry", "queue", "underlying", "ws")

    def __init__(self, ws, underlying: str, expiry: str) -> None:  # type: ignore[no-untyped-def]
        self.ws = ws
        self.underlying = underlying.upper()
        self.expiry = expiry
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        self.addr = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"

    def push(self, payload: str) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
                log.warning("ws_options_client_lagging", addr=self.addr)
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class OptionsHub:
    def __init__(self) -> None:
        self._clients: set[_OptionsClient] = set()

    def add(self, client: _OptionsClient) -> None:
        self._clients.add(client)
        log.info("ws_options_client_connected", addr=client.addr, total=len(self._clients))

    def remove(self, client: _OptionsClient) -> None:
        self._clients.discard(client)
        log.info("ws_options_client_disconnected", addr=client.addr, total=len(self._clients))

    def broadcast(self, underlying: str, expiry: str, snapshot: dict) -> None:
        if not self._clients:
            return
        # Serialise datetime fields for JSON
        serialisable = {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in snapshot.items()
            if k != "_id"
        }
        payload = json.dumps({"type": "snapshot", **serialisable})
        for client in self._clients:
            if client.underlying == underlying.upper() and client.expiry == expiry:
                client.push(payload)

    def make_client(self, ws, underlying: str, expiry: str) -> _OptionsClient:  # type: ignore[no-untyped-def]
        return _OptionsClient(ws, underlying, expiry)
