"""Analysis routes: session narrative on seeded data, 404 when empty."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pdp.observability.routes import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

_SAMPLE_EVENTS = [
    {
        "event_type": "bias_evaluated",
        "ist_time": "2026-06-28T09:15:00+05:30",
        "bucket": "STRONG_BULL",
        "score": 1.8,
        "spot": 24050.0,
        "bias_votes": {"ema_1h": 1, "vwap": 1},
    },
    {
        "event_type": "leg_open",
        "ist_time": "2026-06-28T09:15:30+05:30",
        "opt_type": "CE",
        "strike": 24100.0,
        "lots": 2,
        "entry_price": 90.0,
        "sid": "10001",
    },
]


def test_session_404_when_no_events():
    with patch("pdp.observability.routes.get_opensearch") as mock_get, \
         patch("pdp.observability.routes.fetch_session_events", new_callable=AsyncMock) as mock_fetch:
        mock_get.return_value = AsyncMock()
        mock_fetch.return_value = []
        resp = client.get("/api/v1/analysis/session?date=2026-06-28")
    assert resp.status_code == 404


def test_session_returns_narrative_on_events():
    with patch("pdp.observability.routes.get_opensearch") as mock_get, \
         patch("pdp.observability.routes.fetch_session_events", new_callable=AsyncMock) as mock_fetch:
        mock_get.return_value = AsyncMock()
        mock_fetch.return_value = _SAMPLE_EVENTS
        resp = client.get("/api/v1/analysis/session?date=2026-06-28")

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-06-28"
    assert "bars" in body
    assert len(body["bars"]) >= 1
    assert "summary" in body


def test_session_503_when_disabled():
    with patch("pdp.observability.routes.get_opensearch") as mock_get:
        mock_get.return_value = None
        resp = client.get("/api/v1/analysis/session?date=2026-06-28")
    assert resp.status_code == 503


def test_log_search_503_when_disabled():
    with patch("pdp.observability.routes.get_opensearch") as mock_get:
        mock_get.return_value = None
        resp = client.get("/api/v1/observability/logs?source=api")
    assert resp.status_code == 503
