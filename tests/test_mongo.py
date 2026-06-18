from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from pdp.main import create_app
from pdp.mongo.collections import init_collections
from pdp.settings import Settings

# ------------------------------------------------------------------ #
# init_collections unit tests                                          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_init_collections_creates_market_bars() -> None:
    db = MagicMock()
    db.create_collection = AsyncMock()
    db.__getitem__ = MagicMock(return_value=MagicMock(create_index=AsyncMock()))
    settings = Settings()  # type: ignore[call-arg]

    await init_collections(db, settings)

    db.create_collection.assert_any_call(
        "market_bars",
        timeseries={
            "timeField": "ts",
            "metaField": "metadata",
            "granularity": "seconds",
        },
    )


@pytest.mark.asyncio
async def test_init_collections_creates_option_chains_with_ttl() -> None:
    from pymongo import ASCENDING

    chains_col = MagicMock()
    chains_col.create_index = AsyncMock()
    portfolio_col = MagicMock()
    portfolio_col.create_index = AsyncMock()
    option_bars_col = MagicMock()
    option_bars_col.create_index = AsyncMock()
    positional_col = MagicMock()
    positional_col.create_index = AsyncMock()

    events_col = MagicMock()
    events_col.create_index = AsyncMock()

    def _getitem(name: str):
        if name == "portfolio_snapshots":
            return portfolio_col
        if name == "option_bars":
            return option_bars_col
        if name == "positional_eod_snapshots":
            return positional_col
        if name == "events":
            return events_col
        return chains_col

    db = MagicMock()
    db.create_collection = AsyncMock()
    db.__getitem__ = MagicMock(side_effect=_getitem)
    settings = Settings()  # type: ignore[call-arg]

    await init_collections(db, settings)

    # Three indexes on option_chains: TTL captured_at (legacy), TTL snapshot_ts, compound lookup
    assert chains_col.create_index.call_count == 3
    chains_col.create_index.assert_any_call(
        [("captured_at", ASCENDING)],
        expireAfterSeconds=settings.MONGO_CHAIN_TTL_DAYS * 86400,
        name="ttl_captured_at",
    )
    from pymongo import ASCENDING as ASC
    chains_col.create_index.assert_any_call(
        [("snapshot_ts", ASC)],
        expireAfterSeconds=settings.OPTIONS_CHAIN_TTL_DAYS * 86400,
        name="ttl_snapshot_ts",
    )
    # Two indexes on portfolio_snapshots: TTL snapshot_ts, unique snapshot_date
    assert portfolio_col.create_index.call_count == 2


@pytest.mark.asyncio
async def test_init_collections_creates_option_bars_regular_with_unique_index() -> None:
    from pymongo import ASCENDING

    option_bars_col = MagicMock()
    option_bars_col.create_index = AsyncMock()
    other_col = MagicMock()
    other_col.create_index = AsyncMock()

    db = MagicMock()
    db.create_collection = AsyncMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: option_bars_col if name == "option_bars" else other_col
    )
    settings = Settings()  # type: ignore[call-arg]

    await init_collections(db, settings)

    # Regular collection — created WITHOUT a timeseries kwarg (time-series can't be unique-indexed).
    db.create_collection.assert_any_call("option_bars")
    # Unique contract+ts index makes duplicate bars structurally impossible.
    option_bars_col.create_index.assert_any_call(
        [
            ("underlying", ASCENDING),
            ("expiry_date", ASCENDING),
            ("strike", ASCENDING),
            ("option_type", ASCENDING),
            ("timeframe", ASCENDING),
            ("ts", ASCENDING),
        ],
        unique=True,
        name="uq_contract_ts",
    )


@pytest.mark.asyncio
async def test_init_collections_idempotent_on_existing_collection() -> None:
    from pymongo.errors import CollectionInvalid

    db = MagicMock()
    db.create_collection = AsyncMock(side_effect=CollectionInvalid("already exists"))
    chains_col = MagicMock()
    chains_col.create_index = AsyncMock()
    db.__getitem__ = MagicMock(return_value=chains_col)
    settings = Settings()  # type: ignore[call-arg]

    # Should not raise
    await init_collections(db, settings)


# ------------------------------------------------------------------ #
# /readyz with Mongo                                                   #
# ------------------------------------------------------------------ #


def _make_mock_mongo_db(ping_ok: bool):
    mongo_db = MagicMock()
    if ping_ok:
        mongo_db.command = AsyncMock(return_value={"ok": 1})
    else:
        mongo_db.command = AsyncMock(side_effect=Exception("Connection refused"))
    return mongo_db


def _mock_portfolio_service():
    svc = MagicMock()
    svc.start = AsyncMock()
    svc.stop = AsyncMock()
    svc.subscribe_fill_events = MagicMock()
    svc.get_snapshot = MagicMock(return_value=[])
    return svc


@pytest.mark.asyncio
async def test_readyz_includes_mongo_ok() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    with (
        patch("pdp.main.mongo_connect") as mock_connect,
        patch("pdp.main.init_collections", new=AsyncMock()),
        patch("pdp.main.mongo_disconnect"),
        patch("pdp.main.get_engine") as mock_engine,
        patch("pdp.portfolio.service.PortfolioService", return_value=_mock_portfolio_service()),
    ):
        mock_mongo_db = _make_mock_mongo_db(ping_ok=True)
        mock_connect.return_value = (MagicMock(), mock_mongo_db)

        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=AsyncMock(execute=AsyncMock()))
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.return_value.begin.return_value = conn_ctx

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                with patch.object(app.state, "redis", AsyncMock(ping=AsyncMock())):
                    resp = await client.get("/readyz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mongo"] == "ok"
    assert body["status"] == "ready"


@pytest.mark.asyncio
async def test_readyz_returns_503_when_mongo_down() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    with (
        patch("pdp.main.mongo_connect") as mock_connect,
        patch("pdp.main.init_collections", new=AsyncMock()),
        patch("pdp.main.mongo_disconnect"),
        patch("pdp.main.get_engine") as mock_engine,
        patch("pdp.portfolio.service.PortfolioService", return_value=_mock_portfolio_service()),
    ):
        mock_mongo_db = _make_mock_mongo_db(ping_ok=False)
        mock_connect.return_value = (MagicMock(), mock_mongo_db)

        conn_ctx = AsyncMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=AsyncMock(execute=AsyncMock()))
        conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.return_value.begin.return_value = conn_ctx

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with app.router.lifespan_context(app):
                with patch.object(app.state, "redis", AsyncMock(ping=AsyncMock())):
                    resp = await client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert "error" in body["mongo"]
    assert body["status"] == "degraded"
