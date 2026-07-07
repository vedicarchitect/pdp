"""Unit tests for GET /api/v1/strangle/monitor — payload shape + 404."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdp.strategy.routes import strangle_router


def _make_app(host_mock: MagicMock, redis_mock: MagicMock | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(strangle_router)
    app.state.strategy_host = host_mock
    app.state.redis = redis_mock or MagicMock()
    app.state.indicator_engine = None
    # No mongo_db state → chains_col will be None
    return app


def _host_no_strangle() -> MagicMock:
    """Host with no DirectionalStrangle instances running."""
    host = MagicMock()
    host._running = {}
    return host


def _host_with_strangle() -> MagicMock:
    """Host with a mock DirectionalStrangle returning minimal state()."""
    from pdp.strategies.directional_strangle import DirectionalStrangle

    strategy = MagicMock(spec=DirectionalStrangle)
    strategy.underlying = "NIFTY"
    strategy._activity = []
    strategy.state = AsyncMock(return_value={
        "legs": [],
        "day_realized": 0.0,
        "day_unrealized": 100.0,
        "day_pnl": 100.0,
        "bucket": "neutral",
        "score": 0.1,
        "done_for_day": False,
        "started_at": "2026-06-30T09:15:00+05:30",
        "n_open_shorts": 0,
        "n_open_hedges": 0,
        "n_open_momentum": 0,
    })

    state_obj = MagicMock()
    state_obj.instance = strategy

    host = MagicMock()
    host._running = {"directional_strangle_nifty": state_obj}
    return host


def _redis_no_ltp() -> MagicMock:
    """Redis mock that returns None for all LTP lookups."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    return redis


def test_monitor_404_when_no_strangle_running() -> None:
    host = _host_no_strangle()
    app = _make_app(host)

    with TestClient(app) as client:
        resp = client.get("/api/v1/strangle/monitor")

    assert resp.status_code == 404
    assert "DirectionalStrangle" in resp.json()["detail"]


def test_monitor_payload_shape_with_running_strategy() -> None:
    host = _host_with_strangle()
    redis = _redis_no_ltp()
    app = _make_app(host, redis)

    with TestClient(app) as client:
        resp = client.get("/api/v1/strangle/monitor")

    assert resp.status_code == 200
    data = resp.json()

    # Top-level keys
    assert set(data.keys()) >= {"indices", "groups", "totals", "status", "recent_events", "indicators"}

    # Indices block: 3 known indices
    assert set(data["indices"].keys()) == {"NIFTY", "BANKNIFTY", "SENSEX"}
    for _idx, info in data["indices"].items():
        assert "spot" in info
        assert "future" in info

    # Totals block
    assert "day_realized" in data["totals"]
    assert "day_unrealized" in data["totals"]
    assert "day_pnl" in data["totals"]

    # Status block
    status = data["status"]
    assert "bucket" in status
    assert "score" in status
    assert "done_for_day" in status
    assert "n_open_shorts" in status

    # Indicators block: at minimum the 3 index SIDs
    for sid in ("13", "25", "51"):
        assert sid in data["indicators"]
        assert "tf" in data["indicators"][sid]


def test_monitor_groups_empty_when_no_legs() -> None:
    host = _host_with_strangle()
    redis = _redis_no_ltp()
    app = _make_app(host, redis)

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    # No legs → groups is empty list
    assert data["groups"] == []
    assert data["totals"]["day_unrealized"] == 100.0  # from mock state


def test_monitor_status_sums_across_strategies() -> None:
    """Overall status.done_for_day is True only when all strategies are done."""
    from pdp.strategies.directional_strangle import DirectionalStrangle

    def _make_strategy(underlying: str, done: bool) -> MagicMock:
        s = MagicMock(spec=DirectionalStrangle)
        s.underlying = underlying
        s._activity = []
        s.state = AsyncMock(return_value={
            "legs": [], "day_realized": 0.0, "day_unrealized": 0.0, "day_pnl": 0.0,
            "bucket": None, "score": 0.0, "done_for_day": done,
            "started_at": None, "n_open_shorts": 0, "n_open_hedges": 0, "n_open_momentum": 0,
        })
        return s

    host = MagicMock()
    host._running = {
        "nifty": MagicMock(instance=_make_strategy("NIFTY", done=True)),
        "banknifty": MagicMock(instance=_make_strategy("BANKNIFTY", done=False)),
    }

    app = _make_app(host, _redis_no_ltp())

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    assert data["status"]["done_for_day"] is False
