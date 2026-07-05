"""Integration tests for intel + dashboard REST endpoints: available & unavailable paths."""
from __future__ import annotations

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


def _set_fake_redis(client: TestClient, values: dict[str, str]) -> None:
    async def _get(key):
        return values.get(key)

    fake = MagicMock()
    fake.get = AsyncMock(side_effect=_get)
    fake.aclose = AsyncMock()  # lifespan shutdown awaits this
    client.app.state.redis = fake


# ── intel routes (no poller configured — default test app has INTEL_ENABLED=false) ──

def test_global_indices_unavailable_without_poller(client):
    client.app.state.intel_poller = None
    resp = client.get("/api/v1/intel/global-indices")
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "indices": []}


def test_global_indices_available_with_poller_cache(client):
    poller = MagicMock()
    poller.read_cache = AsyncMock(return_value={
        "as_of": "2026-07-05T10:00:00+00:00",
        "data": [{"symbol": "DOW", "ticker": "^DJI", "close": 100.0, "prev_close": 95.0,
                  "change": 5.0, "change_pct": 5.26}],
    })
    client.app.state.intel_poller = poller
    resp = client.get("/api/v1/intel/global-indices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["indices"][0]["symbol"] == "DOW"


def test_news_unavailable_without_poller(client):
    client.app.state.intel_poller = None
    resp = client.get("/api/v1/intel/news")
    assert resp.json() == {"available": False, "articles": []}


def test_sentiment_unavailable_without_poller(client):
    client.app.state.intel_poller = None
    resp = client.get("/api/v1/intel/sentiment")
    assert resp.json() == {"available": False}


def test_sentiment_available_with_poller_cache(client):
    poller = MagicMock()
    poller.read_cache = AsyncMock(return_value={
        "as_of": "2026-07-05T10:00:00+00:00",
        "data": {"blended_score": 65.0, "label": "Bullish", "news_score": 70.0,
                 "internals_score": 60.0},
    })
    client.app.state.intel_poller = poller
    resp = client.get("/api/v1/intel/sentiment")
    body = resp.json()
    assert body["available"] is True
    assert body["blended_score"] == pytest.approx(65.0)


def test_commodities_unavailable_when_sid_unconfigured(client):
    # Default settings have empty MCX_*_SECURITY_ID
    resp = client.get("/api/v1/intel/commodities")
    assert resp.status_code == 200
    for c in resp.json()["commodities"]:
        assert c["available"] is False


def test_commodities_available_when_sid_configured_and_ticking(client):
    from pdp import settings as settings_module

    with patch.object(settings_module.get_settings(), "MCX_GOLD_SECURITY_ID", "999"):
        _set_fake_redis(client, {"ltp:999": "72500.0"})
        resp = client.get("/api/v1/intel/commodities")
    body = resp.json()
    gold = next(c for c in body["commodities"] if c["symbol"] == "GOLD")
    assert gold["available"] is True
    assert gold["ltp"] == pytest.approx(72500.0)


def test_vix_unavailable_without_tick(client):
    from pdp.settings import get_settings

    _set_fake_redis(client, {})
    resp = client.get("/api/v1/intel/vix")
    assert resp.json() == {"available": False, "security_id": get_settings().VIX_SECURITY_ID}


def test_vix_available_with_tick(client):
    from pdp.settings import get_settings

    sid = get_settings().VIX_SECURITY_ID
    _set_fake_redis(client, {f"ltp:{sid}": "13.5"})
    resp = client.get("/api/v1/intel/vix")
    body = resp.json()
    assert body["available"] is True
    assert body["value"] == pytest.approx(13.5)


def test_next_expiry_returns_per_index_result(client):
    resp = client.get("/api/v1/intel/next-expiry")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["expiries"].keys()) == {"NIFTY", "BANKNIFTY", "SENSEX"}


# ── composed /api/v1/dashboard ───────────────────────────────────────────────

def test_dashboard_returns_every_section_with_no_poller_and_no_data(client):
    client.app.state.intel_poller = None
    client.app.state.journal_service = None
    _set_fake_redis(client, {})
    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "indices", "global_indices", "commodities", "vix", "next_expiry",
        "fii_dii", "news", "sentiment", "portfolio", "today_pnl", "margin", "strategies",
    ):
        assert key in body
    # No ticks cached -> every index degrades honestly, never fabricated
    for idx in body["indices"].values():
        assert idx["available"] is False


def test_dashboard_index_change_is_vs_prev_close(client):
    _set_fake_redis(client, {"ltp:13": "24700.0"})

    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={"close": 24600.0})
    client.app.state.mongo_db.__getitem__ = MagicMock(return_value=mock_col)

    resp = client.get("/api/v1/dashboard")
    body = resp.json()
    nifty = body["indices"]["NIFTY"]
    assert nifty["available"] is True
    assert nifty["prev_close"] == pytest.approx(24600.0)
    assert nifty["change"] == pytest.approx(100.0)
    assert nifty["change_pct"] == pytest.approx(100.0 / 24600.0 * 100)


def test_dashboard_never_blocks_on_third_party_calls(client):
    """No yfinance/nsepython/feedparser import should occur when the poller cache is empty."""
    client.app.state.intel_poller = None
    _set_fake_redis(client, {})
    with patch("yfinance.download", side_effect=AssertionError("must not call yfinance inline")):
        with patch("nsepython.nse_fiidii", side_effect=AssertionError("must not call nsepython inline")):
            resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 200
