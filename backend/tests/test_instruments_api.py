from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pdp.db.session import get_db
from pdp.instruments.models import Instrument
from pdp.main import create_app


def _make_instrument(**overrides) -> Instrument:
    base = dict(
        id=1,
        security_id="13",
        exchange_segment="IDX_I",
        trading_symbol="NIFTY",
        instrument_type="INDEX",
        underlying="NIFTY",
        expiry=None,
        strike=None,
        option_type=None,
        lot_size=1,
        tick_size=0,
        isin=None,
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Instrument(**base)


@pytest.fixture
def app_with_fake_db(monkeypatch):
    app = create_app()
    fake_session = AsyncMock()

    async def fake_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = fake_get_db
    return app, fake_session


@pytest.mark.asyncio
async def test_search_returns_results(app_with_fake_db, monkeypatch):
    app, _ = app_with_fake_db
    nifty = _make_instrument()
    monkeypatch.setattr(
        "pdp.instruments.routes.service.search",
        AsyncMock(return_value=[nifty]),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/v1/instruments?q=NIFTY")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["trading_symbol"] == "NIFTY"
    assert body[0]["exchange_segment"] == "IDX_I"


@pytest.mark.asyncio
async def test_get_by_id_404(app_with_fake_db, monkeypatch):
    app, _ = app_with_fake_db
    monkeypatch.setattr(
        "pdp.instruments.routes.service.get_by_id",
        AsyncMock(return_value=None),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/v1/instruments/9999?segment=NSE_EQ")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "instrument not found"


@pytest.mark.asyncio
async def test_get_by_id_ok(app_with_fake_db, monkeypatch):
    app, _ = app_with_fake_db
    inst = _make_instrument(security_id="1333", exchange_segment="NSE_EQ", trading_symbol="HDFCBANK")
    monkeypatch.setattr(
        "pdp.instruments.routes.service.get_by_id",
        AsyncMock(return_value=inst),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.get("/api/v1/instruments/1333?segment=NSE_EQ")
    assert resp.status_code == 200
    assert resp.json()["trading_symbol"] == "HDFCBANK"
