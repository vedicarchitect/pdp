from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from pdp.main import create_app


@pytest.mark.asyncio
async def test_healthz_returns_ok() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "pdp"
    assert "git_sha" in body
    assert "started_at" in body


@pytest.mark.asyncio
async def test_request_id_header_round_trips() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert resp.headers.get("X-Request-ID") == "abc-123"
