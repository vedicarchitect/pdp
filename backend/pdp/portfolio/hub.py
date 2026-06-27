"""WebSocket hub for portfolio position update broadcasts."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

log = structlog.get_logger()

_CLIENT_QUEUE_SIZE = 20


class _PortfolioClient:
    __slots__ = ("addr", "queue", "ws")

    def __init__(self, ws) -> None:  # type: ignore[no-untyped-def]
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        self.addr = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"

    def push(self, payload: str) -> None:
        if self.queue.full():
            try:
                self.queue.get_nowait()
                log.warning("portfolio_client_lagging", addr=self.addr)
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class PortfolioHub:
    def __init__(self) -> None:
        self._clients: set[_PortfolioClient] = set()

    def add(self, client: _PortfolioClient) -> None:
        self._clients.add(client)
        log.info("ws_portfolio_client_connected", addr=client.addr, total=len(self._clients))

    def remove(self, client: _PortfolioClient) -> None:
        self._clients.discard(client)
        log.info("ws_portfolio_client_disconnected", addr=client.addr, total=len(self._clients))

    def broadcast(self, positions: list[dict], summary: dict[str, Any] | None = None) -> None:
        if not self._clients:
            return
        msg: dict[str, Any] = {"type": "portfolio_update", "positions": positions}
        if summary is not None:
            msg["summary"] = summary
        payload = json.dumps(msg)
        for client in self._clients:
            client.push(payload)

    def make_client(self, ws) -> _PortfolioClient:  # type: ignore[no-untyped-def]
        return _PortfolioClient(ws)
