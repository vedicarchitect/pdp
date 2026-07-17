"""Unit tests for strategy monitor endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdp.strategies.directional_strangle import DirectionalStrangle
from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness
from pdp.strategy.routes import strangle_router


@pytest.fixture
def mock_strategy():
    # Use spec=DirectionalStrangle so the endpoint's isinstance() check passes.
    strategy = MagicMock(spec=DirectionalStrangle)
    strategy.underlying = "NIFTY"
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
    strategy.check_readiness = AsyncMock(
        return_value=StrategyReadiness.evaluate([ReadinessComponent("Indicators", "ok", "seeded")])
    )
    return strategy


def _levels_doc(period: str, h: float, low: float, c: float) -> dict:
    """Minimal index_levels doc matching LevelsStore output shape."""
    rng = h - low
    return {
        "period": period,
        "source": {"h": h, "l": low, "c": c},
        "camarilla": {
            "pp": (h + low + c) / 3,
            "r3": c + rng * 1.1 / 4,
            "r4": c + rng * 1.1 / 2,
            "s3": c - rng * 1.1 / 4,
            "s4": c - rng * 1.1 / 2,
        },
    }


@pytest.fixture
def test_app(mock_strategy):
    app = FastAPI()
    app.include_router(strangle_router)

    # Host with one running DirectionalStrangle.
    running_entry = MagicMock()
    running_entry.instance = mock_strategy
    host = MagicMock()
    host._running = {"null_strat": running_entry}
    app.state.strategy_host = host

    app.state.redis = AsyncMock()
    app.state.indicator_engine = MagicMock()
    app.state.indicator_engine.matrix_futures_sids = {"13": "13_FUT"}
    app.state.indicator_engine.get_ema.return_value = None
    app.state.indicator_engine.get.return_value = None
    app.state.indicator_engine.get_psar.return_value = None
    app.state.indicator_engine.get_rsi.return_value = None
    app.state.indicator_engine.get_vwap.return_value = None
    app.state.indicator_engine.get_vwma.return_value = None

    # option_chains collection — greeks lookup.
    chains_col = AsyncMock()
    chains_col.find_one = AsyncMock(return_value={
        "snapshot_ts": "2026-06-30T09:15:00",
        "underlying": "NIFTY",
        "strikes": [
            {
                "strike": 24000.0,
                "pe": {"delta": -0.25, "vega": 15.0, "gamma": 0.001, "theta": -10.0, "oi": 50000},
            }
        ],
    })

    # index_levels collection — LevelsStore.get(sid, period, date) → find_one by period.
    levels_by_period = {
        "daily": _levels_doc("daily", 24300.0, 24100.0, 24200.0),
        "weekly": _levels_doc("weekly", 24500.0, 23900.0, 24200.0),
        "monthly": _levels_doc("monthly", 24800.0, 23500.0, 24200.0),
    }

    async def _levels_find_one(query, *args, **kwargs):
        return levels_by_period.get(query.get("period"))

    levels_col = AsyncMock()
    levels_col.find_one = AsyncMock(side_effect=_levels_find_one)

    # option_bars collection — ATM CE/PE suite reads. Empty in this fixture (no ATM
    # option data configured), so the ATM rows resolve to {} via the degrade-honestly
    # path rather than fabricating anything.
    class _EmptyCursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    option_bars_col = MagicMock()
    option_bars_col.find.return_value = _EmptyCursor()

    def _getitem(name):
        if name == "index_levels":
            return levels_col
        if name == "option_bars":
            return option_bars_col
        return chains_col

    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = _getitem
    app.state.mongo_db = mock_db

    return app


@pytest.mark.asyncio
async def test_strangle_monitor_endpoint_shape(test_app):
    with (
        patch("pdp.strategy.routes._get_ltp_redis", new_callable=AsyncMock) as mock_ltp,
        patch("pdp.strategy.atm_suite.resolve_nifty_atm_option", new_callable=AsyncMock) as mock_atm,
    ):
        mock_ltp.return_value = 24200.0
        mock_atm.return_value = None  # no instruments-table row in this fixture's world

        with TestClient(test_app) as client:
            resp = client.get("/api/v1/strangle/monitor?strategy_id=null_strat")

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Top level keys
        for key in ("indices", "groups", "totals", "status", "recent_events", "indicators"):
            assert key in data

        # Indices
        assert data["indices"]["NIFTY"]["spot"] == 24200.0
        assert data["indices"]["NIFTY"]["future"] == 24200.0

        # Totals
        assert data["totals"]["day_realized"] == 1000.0
        assert data["totals"]["day_unrealized"] == 1500.0

        # Groups (legs)
        assert len(data["groups"]) == 1
        assert data["groups"][0]["underlying"] == "NIFTY"
        assert data["groups"][0]["legs"][0]["delta"] == -0.25

        # Status + events
        assert data["status"]["bucket"] == "neutral"
        assert len(data["recent_events"]) == 1


@pytest.mark.asyncio
async def test_monitor_levels_from_warehouse(test_app):
    """Matrix Camarilla + period levels come from index_levels (daily/weekly/monthly)."""
    with (
        patch("pdp.strategy.routes._get_ltp_redis", new_callable=AsyncMock) as mock_ltp,
        patch("pdp.strategy.atm_suite.resolve_nifty_atm_option", new_callable=AsyncMock) as mock_atm,
    ):
        mock_ltp.return_value = 24200.0
        mock_atm.return_value = None

        with TestClient(test_app) as client:
            data = client.get("/api/v1/strangle/monitor").json()

        nifty = data["indicators"]["13"]
        # All three Camarilla sets present, sourced from the warehouse docs.
        assert nifty["camarilla_daily"]["r4"] is not None
        assert nifty["camarilla_weekly"]["r4"] is not None
        assert nifty["camarilla_monthly"]["r4"] is not None

        # Period levels = source h/l per period; PDH must differ from PDL and from price.
        period = nifty["period"]
        assert period["pdh"] == 24300.0 and period["pdl"] == 24100.0
        assert period["pwh"] == 24500.0 and period["pwl"] == 23900.0
        assert period["pmh"] == 24800.0 and period["pml"] == 23500.0
        assert period["pdh"] != period["pdl"] != 24200.0
