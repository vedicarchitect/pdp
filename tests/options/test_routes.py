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


def _fake_snapshot_with_strikes() -> dict:
    base = _fake_snapshot()
    base["strikes"] = [
        {"strike": 22500, "ce": {"oi": 1000, "gamma": 0.02}, "pe": {"oi": 800, "gamma": 0.02}},
        {"strike": 22400, "ce": {"oi": 500, "gamma": 0.01}, "pe": {"oi": 600, "gamma": 0.01}},
    ]
    return base


def _mock_find(client: TestClient, docs: list[dict]) -> None:
    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=docs)
    mock_col = MagicMock()
    mock_col.find.return_value = mock_cursor
    client.app.state.mongo_db.__getitem__ = MagicMock(return_value=mock_col)


def test_gex_paper_mode(client):
    resp = client.get("/api/v1/options/NIFTY/gex")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "paper"
    assert body["per_strike"] == []
    assert body["net_gex"] == 0
    assert body["net_gex_cr"] == pytest.approx(0.0)


def test_gex_returns_sorted_per_strike(client):
    client.app.state.options_poller = MagicMock()
    _mock_find_one(client, _fake_snapshot_with_strikes())

    resp = client.get("/api/v1/options/NIFTY/gex?expiry=2026-06-26")
    assert resp.status_code == 200
    body = resp.json()
    assert body["underlying"] == "NIFTY"
    assert "net_gex_cr" in body
    assert body["lot_size"] == 75
    strikes = [s["strike"] for s in body["per_strike"]]
    assert strikes == sorted(strikes)


def test_gex_404_when_no_snapshot(client):
    client.app.state.options_poller = MagicMock()
    _mock_find_one(client, None)

    resp = client.get("/api/v1/options/NIFTY/gex?expiry=2026-06-26")
    assert resp.status_code == 404


def test_oi_history_paper_mode(client):
    resp = client.get("/api/v1/options/NIFTY/oi-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "paper"
    assert body["snapshots"] == []


def test_oi_history_returns_oldest_first(client):
    client.app.state.options_poller = MagicMock()
    ts1 = datetime(2026, 6, 6, 9, 30, tzinfo=UTC)
    ts2 = datetime(2026, 6, 6, 9, 35, tzinfo=UTC)
    # find() sorts desc; route reverses → oldest first
    docs = [
        {**_fake_snapshot(), "snapshot_ts": ts2, "pcr": 1.5},
        {**_fake_snapshot(), "snapshot_ts": ts1, "pcr": 1.2},
    ]
    _mock_find(client, docs)

    resp = client.get("/api/v1/options/NIFTY/oi-history?expiry=2026-06-26")
    assert resp.status_code == 200
    body = resp.json()
    snapshots = body["snapshots"]
    assert len(snapshots) == 2
    assert snapshots[0]["pcr"] == pytest.approx(1.2)
    assert snapshots[1]["pcr"] == pytest.approx(1.5)


def test_oi_history_404_when_no_docs(client):
    client.app.state.options_poller = MagicMock()
    _mock_find(client, [])

    resp = client.get("/api/v1/options/NIFTY/oi-history?expiry=2026-06-26")
    assert resp.status_code == 404


def test_payoff_valid_request(client):
    payload = {
        "legs": [
            {"strike": 24800.0, "expiry": "2026-06-26", "option_type": "CE", "side": "BUY", "lots": 1, "premium": 200.0, "iv": 0.18},
            {"strike": 24800.0, "expiry": "2026-06-26", "option_type": "PE", "side": "BUY", "lots": 1, "premium": 180.0, "iv": 0.18},
        ],
        "spot": 24800.0,
        "lot_size": 75,
    }
    resp = client.post("/api/v1/options/NIFTY/payoff", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "pnl_curve" in body
    assert "breakevens" in body
    assert "net_greeks" in body
    assert "probability_of_profit" in body
    assert len(body["pnl_curve"]) == 200


def test_payoff_empty_legs_returns_422(client):
    payload = {"legs": [], "spot": 24800.0, "lot_size": 75}
    resp = client.post("/api/v1/options/NIFTY/payoff", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert "at least one leg" in str(body).lower()


def test_readymades_returns_at_least_10_strategies(client):
    resp = client.get("/api/v1/options/NIFTY/readymades")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["strategies"]) >= 10
    for s in body["strategies"]:
        assert "name" in s
        assert "legs" in s


def test_fii_dii_stub_returns_unavailable(client):
    # With StubFIIDIISource wired (or as fallback), endpoint returns available: false
    from pdp.options.fii_dii import StubFIIDIISource
    client.app.state.fii_dii_source = StubFIIDIISource()

    resp = client.get("/api/v1/options/fii-dii")
    assert resp.status_code == 200
    assert resp.json() == {"available": False}
