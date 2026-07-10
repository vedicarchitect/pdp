"""A disabled subsystem and a flat account must not look the same to a client."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from pdp.main import create_app

READ_ENDPOINTS = [
    "/api/v1/broker-sync/holdings",
    "/api/v1/broker-sync/positions",
    "/api/v1/broker-sync/funds",
]


class _FakeService:
    account_id = "TEST_ACCT"
    has_credentials = True
    live_mode = False

    async def last_run(self) -> dict[str, Any] | None:
        return None

    async def last_state_refresh(self) -> str | None:
        return None


async def _get(app: Any, url: str) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url)


@pytest.mark.parametrize("url", READ_ENDPOINTS)
@pytest.mark.asyncio
async def test_read_endpoints_503_when_sync_disabled(url: str) -> None:
    app = create_app()  # no lifespan → broker_sync_service never constructed
    resp = await _get(app, url)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "broker sync not enabled"


@pytest.mark.asyncio
async def test_status_reports_disabled_without_service() -> None:
    app = create_app()
    resp = await _get(app, "/api/v1/broker-sync/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["last_run"] is None


@pytest.mark.asyncio
async def test_status_reports_enabled_but_never_run() -> None:
    app = create_app()
    app.state.broker_sync_service = _FakeService()
    resp = await _get(app, "/api/v1/broker-sync/status")
    body = resp.json()
    assert body["enabled"] is True
    assert body["has_credentials"] is True
    assert body["live_mode"] is False
    assert body["last_run"] is None
    assert body["last_state_refresh_at"] is None


@pytest.mark.parametrize("url", READ_ENDPOINTS)
@pytest.mark.asyncio
async def test_read_endpoints_200_when_enabled(url: str) -> None:
    """Enabled with an empty mirror is a legitimate 200 — `/status` disambiguates."""
    app = create_app()
    app.state.broker_sync_service = _FakeService()
    resp = await _get(app, url)
    assert resp.status_code == 200
    assert "items" in resp.json()
