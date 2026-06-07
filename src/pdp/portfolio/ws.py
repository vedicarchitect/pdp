"""Portfolio WebSocket endpoint."""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pdp.portfolio.hub import PortfolioHub, _PortfolioClient

log = structlog.get_logger()

portfolio_ws_router = APIRouter(tags=["portfolio-ws"])


async def _pump(client: _PortfolioClient) -> None:
    while True:
        msg = await client.queue.get()
        await client.ws.send_text(msg)


@portfolio_ws_router.websocket("/ws/portfolio")
async def portfolio_ws(ws: WebSocket) -> None:
    await ws.accept()

    hub: PortfolioHub = ws.app.state.portfolio_hub
    client = hub.make_client(ws)
    hub.add(client)

    # Push initial snapshot from in-memory cache
    service = getattr(ws.app.state, "portfolio_service", None)
    if service is not None:
        snapshot = service.get_snapshot()
        summary = service._build_summary()
        initial = json.dumps({"type": "portfolio_update", "positions": snapshot, "summary": summary})
        client.push(initial)

    pump_task = asyncio.create_task(_pump(client), name=f"portfolio-ws-pump-{client.addr}")

    try:
        while True:
            await ws.receive_text()  # keep-alive; ignore client messages
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_portfolio_client_error", addr=client.addr, exc=str(exc))
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        hub.remove(client)
