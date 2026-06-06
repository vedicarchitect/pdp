"""Integration tests for options REST endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pdp.main import create_app


@pytest.fixture
def client(mock_mongo_lifespan):
    app = create_app()
    with patch("pdp.market.bar_writer.BarWriter.start", new=AsyncMock()):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _fake_snapshot() -> dict:
    return {
        "underlying": "NIFTY",
        "expiry": "2026-06-26",
        "snapshot_ts": datetime(2026, 6, 6, 9, 30, tzinfo=UTC),
        "spot_price": 22500.0,
        "max_pain": 22400,
        "pcr": 1.23,
        "strikes": [],
    }


def _mock_find_one(client: TestClient, doc: dict | None) -> None:
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value=doc)
    client.app.state.mongo_db.__getitem__ = MagicMock(return_value=mock_col)


def test_chain_paper_mode_when_poller_not_set(client):
    # By default in tests, options_poller is None (set in lifespan to None when not live)
    resp = client.get("/api/v1/options/NIFTY/chain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "paper"
    assert body["strikes"] == []


def test_chain_returns_snapshot_when_poller_active(client):
    client.app.state.options_poller = MagicMock()  # simulate active poller
    _mock_find_one(client, _fake_snapshot())

    resp = client.get("/api/v1/options/NIFTY/chain?expiry=2026-06-26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["underlying"] == "NIFTY"
    assert body["max_pain"] == 22400
    assert body["pcr"] == 1.23


def test_chain_404_when_no_snapshot(client):
    client.app.state.options_poller = MagicMock()
    _mock_find_one(client, None)

    resp = client.get("/api/v1/options/NIFTY/chain?expiry=2026-06-26")
    assert resp.status_code == 404


def test_max_pain_endpoint(client):
    client.app.state.options_poller = MagicMock()
    _mock_find_one(client, _fake_snapshot())

    resp = client.get("/api/v1/options/NIFTY/max-pain?expiry=2026-06-26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_pain"] == 22400
    assert body["underlying"] == "NIFTY"


def test_pcr_endpoint(client):
    client.app.state.options_poller = MagicMock()
    _mock_find_one(client, _fake_snapshot())

    resp = client.get("/api/v1/options/NIFTY/pcr?expiry=2026-06-26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pcr"] == pytest.approx(1.23)
