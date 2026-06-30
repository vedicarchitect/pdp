"""Unit tests for strategy monitor endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdp.strategy.routes import strangle_router


@pytest.fixture
def mock_strategy():
    strategy = MagicMock()
    strategy.underlying = "NIFTY"
    strategy._futures_sid = "13_FUT"
    strategy.state = AsyncMock(return_value={
        "legs": [
            {
                "id": "leg_1",
                "security_id": "13_24000_PE",
                "strike": 24000.0,
                "opt_type": "PE",
                "is_hedge": False,
                "is_momentum": False,
                "mtm": 1500.0,
                "lots": 2,
            }
        ],
        "day_realized": 1000.0,
        "day_unrealized": 1500.0,
        "day_pnl": 2500.0,
        "bucket": "neutral",
        "score": 0.5,
        "done_for_day": False,
        "started_at": "2026-06-30T09:15:00",
        "n_open_shorts": 1,
        "n_open_hedges": 0,
        "n_open_momentum": 0,
    })
    strategy._activity = [{"event_type": "square_off", "ts": "2026-06-30T10:00:00"}]
    return strategy


@pytest.fixture
def test_app(mock_strategy):
    app = FastAPI()
    app.include_router(strangle_router)
    
    app.state.redis = AsyncMock()
    app.state.indicator_engine = MagicMock()
    app.state.indicator_engine.get_ema.return_value = None
    app.state.indicator_engine.get.return_value = None
    app.state.indicator_engine.get_psar.return_value = None
    app.state.indicator_engine.get_pivots.return_value = None
    app.state.indicator_engine.get_levels.return_value = None
    app.state.indicator_engine.get_period_levels.return_value = None
    
    mock_db = MagicMock()
    mock_chains_col = AsyncMock()
    mock_chains_col.find_one = AsyncMock(return_value={
        "snapshot_ts": "2026-06-30T09:15:00",
        "underlying": "NIFTY",
        "strikes": [
            {
                "strike": 24000.0,
                "pe": {
                    "delta": -0.25,
                    "vega": 15.0,
                    "gamma": 0.001,
                    "theta": -10.0,
                    "oi": 50000,
                }
            }
        ]
    })
    mock_db.__getitem__.return_value = mock_chains_col
    app.state.mongo_db = mock_db
    
    return app


@pytest.mark.asyncio
async def test_strangle_monitor_endpoint_shape(test_app, mock_strategy):
    with patch("pdp.strategy.routes._get_strangle", return_value=mock_strategy):
        with patch("pdp.strategy.routes._get_ltp_redis", new_callable=AsyncMock) as mock_ltp:
            mock_ltp.return_value = 24200.0
            
            with TestClient(test_app) as client:
                resp = client.get("/api/v1/strangle/monitor?strategy_id=null_strat")
                
            assert resp.status_code == 200, resp.text
            data = resp.json()
            
            # Check top level keys
            assert "indices" in data
            assert "groups" in data
            assert "totals" in data
            assert "status" in data
            assert "recent_events" in data
            assert "indicators" in data
            
            # Check indices
            assert "NIFTY" in data["indices"]
            assert data["indices"]["NIFTY"]["spot"] == 24200.0
            assert data["indices"]["NIFTY"]["future"] == 24200.0
            
            # Check totals
            assert data["totals"]["day_realized"] == 1000.0
            assert data["totals"]["day_unrealized"] == 1500.0
            
            # Check groups (legs)
            assert len(data["groups"]) == 1
            assert data["groups"][0]["underlying"] == "NIFTY"
            assert len(data["groups"][0]["legs"]) == 1
            assert data["groups"][0]["legs"][0]["delta"] == -0.25
            
            # Check status
            assert data["status"]["bucket"] == "neutral"
            
            # Check events
            assert len(data["recent_events"]) == 1
