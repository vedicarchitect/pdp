"""Unit tests for GET /api/v1/strangle/monitor — payload shape + 404."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness
from pdp.strategy.routes import strangle_router


def _ok_readiness() -> StrategyReadiness:
    return StrategyReadiness.evaluate([ReadinessComponent("Indicators", "ok", "seeded")])


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
    strategy.check_readiness = AsyncMock(return_value=_ok_readiness())

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


def _redis_with_fresh_tick(security_id: str, ts_epoch: float) -> MagicMock:
    """Redis mock where only ltp_ts:{security_id} resolves, for spot_age_s assertions."""
    async def _get(key: str):
        if key == f"ltp_ts:{security_id}":
            return str(ts_epoch)
        return None

    redis = MagicMock()
    redis.get = AsyncMock(side_effect=_get)
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
    assert set(data.keys()) >= {
        "as_of", "indices", "groups", "totals", "status", "recent_events", "indicators",
    }

    # as_of: server build timestamp, so the client can tell a live payload from a stuck poll
    assert data["as_of"]

    # Indices block: 3 known indices
    assert set(data["indices"].keys()) == {"NIFTY", "BANKNIFTY", "SENSEX"}
    for _idx, info in data["indices"].items():
        assert "spot" in info
        assert "future" in info
        # No tick within the last 5s (redis mock returns None) → None, not a stale guess
        assert info["spot_age_s"] is None

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

    # Readiness: composite state + per-underlying breakdown, nested under status
    readiness = status["readiness"]
    assert readiness["state"] == "ok"
    assert readiness["by_underlying"]["NIFTY"]["state"] == "ok"


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
        s.check_readiness = AsyncMock(return_value=_ok_readiness())
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


def test_monitor_readiness_is_worst_case_across_strategies() -> None:
    """Overall readiness.state is the worst of any running strategy's own state —
    one blocked underlying must not be hidden by another that's fine."""
    from pdp.strategies.directional_strangle import DirectionalStrangle
    from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness

    def _make_strategy(underlying: str, readiness: StrategyReadiness) -> MagicMock:
        s = MagicMock(spec=DirectionalStrangle)
        s.underlying = underlying
        s._activity = []
        s.state = AsyncMock(return_value={
            "legs": [], "day_realized": 0.0, "day_unrealized": 0.0, "day_pnl": 0.0,
            "bucket": None, "score": 0.0, "done_for_day": False,
            "started_at": None, "n_open_shorts": 0, "n_open_hedges": 0, "n_open_momentum": 0,
        })
        s.check_readiness = AsyncMock(return_value=readiness)
        return s

    blocked = StrategyReadiness.evaluate(
        [ReadinessComponent("Reconciliation", "blocked", "1 leg(s) diverged")]
    )
    host = MagicMock()
    host._running = {
        "nifty": MagicMock(instance=_make_strategy("NIFTY", _ok_readiness())),
        "banknifty": MagicMock(instance=_make_strategy("BANKNIFTY", blocked)),
    }

    app = _make_app(host, _redis_no_ltp())

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    readiness = data["status"]["readiness"]
    assert readiness["state"] == "blocked"
    assert readiness["by_underlying"]["NIFTY"]["state"] == "ok"
    assert readiness["by_underlying"]["BANKNIFTY"]["state"] == "blocked"


def _leg(expiry: str | None = None, **over) -> dict:
    base = {
        "security_id": "63944", "opt_type": "PE", "strike": 24100.0, "lots": 6,
        "entry_price": 100.0, "entry_time": None, "entry_reason": "neutral@0.10",
        "expiry": expiry, "ltp": 90.0, "mtm": 60.0, "day_high": None, "day_low": None,
        "is_hedge": False, "is_momentum": True, "origin": "system",
    }
    base.update(over)
    return base


def test_monitor_leg_carries_expiry_and_server_computed_dte() -> None:
    """A leg with a resolved expiry gets `expiry` passed through and a server-computed
    `dte` (calendar days from IST-today), so the client needs no date library
    (strangle-execution-expiry-and-combined-pnl)."""
    from datetime import UTC, datetime, timedelta

    from pdp.strategies.directional_strangle import DirectionalStrangle

    today_ist = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    expiry = (today_ist + timedelta(days=3)).isoformat()

    strategy = MagicMock(spec=DirectionalStrangle)
    strategy.underlying = "NIFTY"
    strategy._activity = []
    strategy.state = AsyncMock(return_value={
        "legs": [_leg(expiry=expiry), _leg(expiry=None, security_id="63951")],
        "day_realized": 0.0, "day_unrealized": 60.0, "day_pnl": 60.0,
        "bucket": "neutral", "score": 0.1, "done_for_day": False,
        "started_at": None, "n_open_shorts": 0, "n_open_hedges": 0, "n_open_momentum": 2,
    })
    strategy.check_readiness = AsyncMock(return_value=_ok_readiness())

    host = MagicMock()
    host._running = {"nifty": MagicMock(instance=strategy)}
    app = _make_app(host, _redis_no_ltp())

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    legs = data["groups"][0]["legs"]
    with_exp = next(l for l in legs if l["expiry"] == expiry)
    assert with_exp["dte"] == 3
    no_exp = next(l for l in legs if l["expiry"] is None)
    assert no_exp["dte"] is None


def test_monitor_group_totals_use_real_per_underlying_realized() -> None:
    """Per-group `day_realized` reflects the strategy's real realized P&L (not a
    hardcoded 0.0); `day_pnl` = realized + unrealized."""
    from pdp.strategies.directional_strangle import DirectionalStrangle

    strategy = MagicMock(spec=DirectionalStrangle)
    strategy.underlying = "NIFTY"
    strategy._activity = []
    strategy.state = AsyncMock(return_value={
        "legs": [_leg()],  # one leg, mtm=60.0 → unrealized 60
        "day_realized": 1234.5, "day_unrealized": 60.0, "day_pnl": 1294.5,
        "bucket": "neutral", "score": 0.1, "done_for_day": False,
        "started_at": None, "n_open_shorts": 0, "n_open_hedges": 0, "n_open_momentum": 1,
    })
    strategy.check_readiness = AsyncMock(return_value=_ok_readiness())

    host = MagicMock()
    host._running = {"nifty": MagicMock(instance=strategy)}
    app = _make_app(host, _redis_no_ltp())

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    totals = data["groups"][0]["totals"]
    assert totals["day_realized"] == 1234.5
    assert totals["day_unrealized"] == 60.0
    assert totals["day_pnl"] == 1294.5


def test_monitor_spot_age_reflects_seconds_since_last_tick() -> None:
    """A live NIFTY feed (ltp_ts:13 set ~2s ago) reports a small spot_age_s, not None —
    this is the freshness signal the execution panel uses to distinguish a live snapshot
    from a stuck one (see execution-panel-freshness-and-events)."""
    host = _host_with_strangle()
    ts_two_seconds_ago = time.time() - 2.0
    redis = _redis_with_fresh_tick("13", ts_two_seconds_ago)
    app = _make_app(host, redis)

    with TestClient(app) as client:
        data = client.get("/api/v1/strangle/monitor").json()

    age = data["indices"]["NIFTY"]["spot_age_s"]
    assert age is not None
    assert 0 <= age < 10
    # BANKNIFTY/SENSEX never ticked in this mock → no stale guess, an honest None
    assert data["indices"]["BANKNIFTY"]["spot_age_s"] is None
    assert data["indices"]["SENSEX"]["spot_age_s"] is None
