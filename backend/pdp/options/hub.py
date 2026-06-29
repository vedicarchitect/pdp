"""WebSocket hub for options chain snapshot broadcasts."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

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
        # Non-WS listeners (e.g. the event publisher) invoked on every snapshot.
        self._listeners: list[Callable[[str, dict[str, Any]], None]] = []
        # Latest PCR per underlying; updated on every broadcast.
        self._pcr: dict[str, float | None] = {}

    def register_listener(self, cb: Callable[[str, dict[str, Any]], None]) -> None:
        """Register ``cb(underlying, snapshot)`` run on each broadcast."""
        self._listeners.append(cb)

    def get_pcr(self, underlying: str) -> float | None:
        """Return the most recently broadcast PCR for *underlying*, or None."""
        return self._pcr.get(underlying.upper())

    def add(self, client: _OptionsClient) -> None:
        self._clients.add(client)
        log.info("ws_options_client_connected", addr=client.addr, total=len(self._clients))

    def remove(self, client: _OptionsClient) -> None:
        self._clients.discard(client)
        log.info("ws_options_client_disconnected", addr=client.addr, total=len(self._clients))

    def broadcast(self, underlying: str, expiry: str, snapshot: dict) -> None:
        pcr = snapshot.get("pcr")
        if pcr is not None:
            try:
                self._pcr[underlying.upper()] = float(pcr)
            except (TypeError, ValueError):
                pass
        for cb in self._listeners:
            try:
                cb(underlying, snapshot)
            except Exception as exc:  # never let a listener break WS fan-out
                log.warning("options_hub_listener_error", exc=str(exc))
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
