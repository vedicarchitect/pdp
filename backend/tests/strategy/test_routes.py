"""Integration tests for strategy REST API lifecycle."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pdp.strategy.abc import Strategy
from pdp.strategy.context import StrategyContext
from pdp.strategy.host import StrategyHost


class _NullStrategy(Strategy):
    async def on_init(self, ctx: StrategyContext) -> None:
        pass


YAML_CONTENT = (
    "id: null_strat\n"
    "class: tests.strategy.test_routes._NullStrategy\n"
    "watchlist:\n"
    "  - security_id: '1333'\n"
    "    exchange_segment: NSE_EQ\n"
    "    timeframes: [1m]\n"
)


@pytest.fixture
def strategies_dir(tmp_path: Path) -> Path:
    (tmp_path / "null_strat.yaml").write_text(YAML_CONTENT)
    return tmp_path


@pytest.fixture
def test_client(strategies_dir):
    """TestClient with a real StrategyHost wired in (DB/Redis patched out)."""
    with (
        patch("pdp.db.session.get_engine"),
        patch("pdp.db.session.get_session_maker"),
        patch("pdp.orders.paper.PaperBroker.start", new_callable=lambda: lambda self, *a, **kw: AsyncMock()()),
        patch("pdp.orders.paper.PaperBroker._load_open_orders", new_callable=lambda: lambda self: AsyncMock()()),
        patch("pdp.orders.paper.PaperBroker._load_costs", new_callable=lambda: lambda self: AsyncMock()()),
        patch("pdp.portfolio.service.PortfolioService.start", new=AsyncMock()),
        patch("pdp.portfolio.service.PortfolioService.stop", new=AsyncMock()),
    ):
        from pdp.main import create_app

        app = create_app()

        host = StrategyHost(
            strategies_dir=strategies_dir,
            order_router=MagicMock(),
            session_maker=MagicMock(),
        )
        host.load_registry()
        app.state.strategy_host = host

        with TestClient(app, raise_server_exceptions=True) as client:
            yield client


# ---------------------------------------------------------------------------
# 8.6 — REST lifecycle
# ---------------------------------------------------------------------------

def test_list_strategies_returns_all(strategies_dir):
    # `strategies_dir` (the fixture) holds a real `null_strat.yaml`, so the unified registry
    # (merged with the mocked host's running-state) picks it up for real, alongside whatever
    # real `backtest/configs/*.yaml` entries exist in this repo checkout — hence asserting on
    # the one entry we care about rather than the total count.
    mock_host = MagicMock()
    mock_host.strategies_dir = strategies_dir
    mock_host.list_all.return_value = [
        {
            "id": "null_strat",
            "status": "STOPPED",
            "dropped_ticks": 0,
            "watchlist": [{"security_id": "1333", "exchange_segment": "NSE_EQ", "timeframes": ["1m"]}],
        }
    ]

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy.routes import router

    app = FastAPI()
    app.include_router(router)
    app.state.strategy_host = mock_host

    with TestClient(app) as c:
        resp = c.get("/api/v1/strategies")
    assert resp.status_code == 200
    data = resp.json()
    by_id = {s["id"]: s for s in data["strategies"]}
    assert by_id["null_strat"]["status"] == "STOPPED"
    assert by_id["null_strat"]["source"] == "live"
    assert by_id["null_strat"]["watchlist"] == [
        {"security_id": "1333", "exchange_segment": "NSE_EQ", "timeframes": ["1m"]}
    ]


@pytest.mark.asyncio
async def test_start_stop_lifecycle(strategies_dir):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy.routes import router

    host = StrategyHost(
        strategies_dir=strategies_dir,
        order_router=MagicMock(),
        session_maker=MagicMock(),
    )
    host.load_registry()

    app = FastAPI()
    app.include_router(router)
    app.state.strategy_host = host

    with TestClient(app) as c:
        resp = c.post("/api/v1/strategies/null_strat/start")
        assert resp.status_code == 200

        # Double-start returns 409
        resp2 = c.post("/api/v1/strategies/null_strat/start")
        assert resp2.status_code == 409
        assert "already running" in resp2.json()["detail"]

        resp3 = c.post("/api/v1/strategies/null_strat/stop")
        assert resp3.status_code == 200

        # Stop again returns 409
        resp4 = c.post("/api/v1/strategies/null_strat/stop")
        assert resp4.status_code == 409
        assert "not running" in resp4.json()["detail"]


def test_register_strategy_route(tmp_path, monkeypatch):
    from functools import partial

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy import routes, unified_registry

    # Redirect the route's registration writes into tmp_path — never touch the real
    # backend/backtest/configs/ directory from a test.
    monkeypatch.setattr(
        routes.unified_registry, "register_strategy",
        partial(unified_registry.register_strategy, configs_dir=tmp_path),
    )

    app = FastAPI()
    app.include_router(routes.router)
    app.state.strategy_host = MagicMock()

    with TestClient(app) as c:
        resp = c.post("/api/v1/strategies/register", json={
            "strategy_id": "test_new_strat",
            "kind": "strangle",
            "params": {"underlying": "NIFTY", "timeframe_min": 15},
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "test_new_strat"
        assert body["underlying"] == "NIFTY"
        assert (tmp_path / "test_new_strat.yaml").exists()

        # Duplicate id -> 422 (already registered, per register_strategy's own id check)
        resp2 = c.post("/api/v1/strategies/register", json={
            "strategy_id": "test_new_strat", "kind": "strangle", "params": {},
        })
        assert resp2.status_code == 422
        assert "already registered" in resp2.json()["detail"]

        # Unknown kind -> 422
        resp3 = c.post("/api/v1/strategies/register", json={
            "strategy_id": "another_strat", "kind": "bogus", "params": {},
        })
        assert resp3.status_code == 422


@pytest.mark.asyncio
async def test_start_unknown_class_returns_422(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pdp.strategy.routes import router

    bad_yaml = (
        "id: bad\n"
        "class: pdp.strategies.does_not_exist.Foo\n"
        "watchlist:\n"
        "  - security_id: '1333'\n"
        "    exchange_segment: NSE_EQ\n"
        "    timeframes: [1m]\n"
    )
    (tmp_path / "bad.yaml").write_text(bad_yaml)

    host = StrategyHost(
        strategies_dir=tmp_path,
        order_router=MagicMock(),
        session_maker=MagicMock(),
    )
    host.load_registry()

    app = FastAPI()
    app.include_router(router)
    app.state.strategy_host = host

    with TestClient(app) as c:
        resp = c.post("/api/v1/strategies/bad/start")
    assert resp.status_code == 422
