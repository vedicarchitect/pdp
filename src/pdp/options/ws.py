"""Options chain WebSocket endpoint."""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pdp.options.hub import OptionsHub, _OptionsClient

log = structlog.get_logger()

options_ws_router = APIRouter(tags=["options-ws"])


async def _pump(client: _OptionsClient) -> None:
    while True:
        msg = await client.queue.get()
        await client.ws.send_text(msg)


@options_ws_router.websocket("/ws/options")
async def options_ws(ws: WebSocket) -> None:
    await ws.accept()

    hub: OptionsHub = ws.app.state.options_hub

    # Wait for subscribe message to know underlying + expiry
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
        msg = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError, Exception):
        await ws.close(code=1008)
        return

    underlying = msg.get("underlying", "")
    expiry = msg.get("expiry", "")
    if not underlying or not expiry or msg.get("action") != "subscribe":
        await ws.close(code=1008)
        return

    client = hub.make_client(ws, underlying, expiry)
    hub.add(client)
    pump_task = asyncio.create_task(_pump(client), name=f"options-ws-pump-{client.addr}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("action") == "unsubscribe":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_options_client_error", addr=client.addr, exc=str(exc))
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        hub.remove(client)
