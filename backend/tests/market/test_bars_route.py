"""Integration tests for GET /api/v1/bars — MongoDB-backed route."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pdp.main import create_app


def _make_mongo_doc(security_id: str, timeframe: str, bar_time: str) -> dict:
    return {
        "_id": "fake_id",
        "ts": datetime.fromisoformat(bar_time).replace(tzinfo=UTC),
        "metadata": {"security_id": security_id, "timeframe": timeframe},
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": 103.0,
        "volume": 500,
        "oi": 0,
    }


class _AsyncCursor:
    """Minimal async cursor that yields a fixed list of documents."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for doc in self._docs:
            yield doc


@pytest.fixture
def client(mock_mongo_lifespan):
    """TestClient with lifespan running (Mongo already patched by autouse fixture)."""
    app = create_app()

    # Patch BarWriter.start so the market feed branch doesn't need real creds
    with patch("pdp.market.bar_writer.BarWriter.start", new=AsyncMock()):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _set_mongo_find(client: TestClient, docs: list[dict]) -> MagicMock:
    """Wire mongo_db["market_bars"].find() to return an async cursor over docs."""
    mock_bars_col = MagicMock()
    mock_bars_col.find.return_value = _AsyncCursor(docs)
    client.app.state.mongo_db.__getitem__ = MagicMock(return_value=mock_bars_col)
    return mock_bars_col


def test_get_bars_returns_docs(client):
    docs = [
        _make_mongo_doc("13", "5m", "2026-01-02T03:50:00"),
        _make_mongo_doc("13", "5m", "2026-01-02T03:45:00"),
    ]
    col = _set_mongo_find(client, docs)

    resp = client.get("/api/v1/bars/13?tf=5m&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["security_id"] == "13"
    assert body[0]["timeframe"] == "5m"
    assert body[0]["bar_time"] == "2026-01-02T03:50:00+00:00"
    col.find.assert_called_once_with(
        {"metadata.security_id": "13", "metadata.timeframe": "5m"},
        sort=[("ts", -1)],
        limit=2,
    )


def test_get_bars_empty(client):
    _set_mongo_find(client, [])
    resp = client.get("/api/v1/bars/99999?tf=5m")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_bars_invalid_timeframe(client):
    resp = client.get("/api/v1/bars/13?tf=7m")
    assert resp.status_code == 422
