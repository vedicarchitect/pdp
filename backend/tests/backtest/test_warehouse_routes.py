"""FastAPI TestClient tests for /api/v1/strangle-backtests warehouse routes.

Uses a patched app.state.mongo_db so no live Mongo is needed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from pdp.db.session import get_db
from pdp.main import create_app


# ── Mongo stubs ───────────────────────────────────────────────────────────────


def _cursor(docs: list[dict]) -> MagicMock:
    """Async-compatible stub for a Motor cursor chain (.find().sort().skip().limit())."""
    c = MagicMock()
    c.sort.return_value = c
    c.skip.return_value = c
    c.limit.return_value = c
    c.to_list = AsyncMock(return_value=docs)
    return c


def _make_mongo_db(
    runs: list[dict], days: list[dict], folds: list[dict], trades: list[dict],
    decisions: list[dict] | None = None,
):
    """Build a stable dict-keyed mock DB so tests can override individual collection methods."""
    col_runs = MagicMock()
    col_runs.find.return_value = _cursor(runs)
    col_runs.find_one = AsyncMock(return_value=runs[0] if runs else None)
    col_runs.count_documents = AsyncMock(return_value=len(runs))
    col_runs.update_one = AsyncMock()

    col_days = MagicMock()
    col_days.find.return_value = _cursor(days)

    col_folds = MagicMock()
    col_folds.find.return_value = _cursor(folds)

    col_trades = MagicMock()
    col_trades.find_one = AsyncMock(return_value=trades[0] if trades else None)

    col_promotions = MagicMock()
    col_promotions.insert_one = AsyncMock()
    col_promotions.update_one = AsyncMock()
    col_promotions.find_one = AsyncMock(return_value=None)

    col_decisions = MagicMock()
    col_decisions.find.return_value = _cursor(decisions or [])

    col_sweeps = MagicMock()
    col_sweeps.find.return_value = _cursor([])
    col_sweeps.count_documents = AsyncMock(return_value=0)

    _cols = {
        "backtest_runs": col_runs,
        "backtest_days": col_days,
        "backtest_folds": col_folds,
        "backtest_trades": col_trades,
        "backtest_promotions": col_promotions,
        "backtest_decisions": col_decisions,
        "backtest_sweeps": col_sweeps,
    }

    db = MagicMock()
    db.__getitem__.side_effect = lambda name: _cols.get(name, MagicMock())
    # Expose for test overrides
    db._cols = _cols
    return db


_RUN = {
    "run_id": "strangle_test1",
    "kind": "single",
    "strategy_id": "strangle",
    "config": {"timeframe_min": 5, "underlying": "NIFTY"},
    "window": {"from": "2026-01-02", "to": "2026-01-10"},
    "metrics": {"net": 10000.0, "profit_factor": 3.0, "max_dd": 2000.0},
    "verdict": None,
    "promotion_state": "none",
    "created_at": datetime.now(UTC),
}

_DAY = {
    "run_id": "strangle_test1",
    "date": "2026-01-02",
    "net": 2000.0,
    "cum_equity": 2000.0,
    "peak": 2000.0,
    "drawdown": 0.0,
}

_FOLD = {
    "run_id": "strangle_test1",
    "fold_index": 0,
    "pick_label": "tren/cons/tp0.5/H",
    "is_metrics": {"net": 500000.0},
    "oos_metrics": {"net": 200000.0},
}

_TRADE_DOC = {
    "run_id": "strangle_test1",
    "date": "2026-01-02",
    "fills": [{"time": "10:15", "side": "SELL", "opt_type": "PE",
               "strike": 23000.0, "qty": 1, "price": 80.0}],
}


@pytest.fixture()
def client(monkeypatch):
    """TestClient with mocked Mongo and job runner state."""
    app = create_app()

    mongo_db = _make_mongo_db([_RUN], [_DAY], [_FOLD], [_TRADE_DOC])

    # Mock job runner
    job_mock = MagicMock()
    job_mock.id = UUID("12345678-1234-5678-1234-567812345678")
    job_mock.status = "PENDING"
    job_runner = MagicMock()
    job_runner.submit = AsyncMock(return_value=job_mock)

    with TestClient(app, raise_server_exceptions=True) as c:
        app.state.mongo_db = mongo_db
        app.state.job_runner = job_runner
        yield c


# ── list runs ─────────────────────────────────────────────────────────────────


def test_list_runs_default(client):
    resp = client.get("/api/v1/strangle-backtests/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert data["total"] >= 0


def test_list_runs_with_kind_filter(client):
    resp = client.get("/api/v1/strangle-backtests/runs?kind=single")
    assert resp.status_code == 200


def test_list_runs_sort_by_pf(client):
    resp = client.get("/api/v1/strangle-backtests/runs?sort_by=pf&sort_dir=-1")
    assert resp.status_code == 200


# ── run detail ───────────────────────────────────────────────────────────────


def test_get_run_detail(client):
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "strangle_test1"
    assert data["kind"] == "single"
    assert "metrics" in data


def test_get_run_not_found(client):
    # Override find_one to return None via the stable _cols dict
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=None)
    resp = client.get("/api/v1/strangle-backtests/runs/nonexistent")
    assert resp.status_code == 404


# ── equity ───────────────────────────────────────────────────────────────────


def test_get_run_equity(client):
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/equity")
    assert resp.status_code == 200
    data = resp.json()
    assert "equity" in data
    assert len(data["equity"]) >= 1
    eq = data["equity"][0]
    assert "date" in eq
    assert "cum_equity" in eq


# ── days ──────────────────────────────────────────────────────────────────────


def test_get_run_days(client):
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days")
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data


# ── folds ─────────────────────────────────────────────────────────────────────


def test_get_run_folds(client):
    # Override find_one on backtest_runs to return a walkforward run with verdict
    wf_run = {**_RUN, "kind": "walkforward", "verdict": "PASS",
               "stitched_oos": {"net": 500000.0, "folds": 4}}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=wf_run)
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/folds")
    assert resp.status_code == 200
    data = resp.json()
    assert "folds" in data
    assert data["verdict"] == "PASS"
    assert "stitched_oos" in data


# ── day trades ────────────────────────────────────────────────────────────────


def test_get_day_trades(client):
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days/2026-01-02/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert "fills" in data
    assert len(data["fills"]) >= 1


def test_get_day_trades_not_found(client):
    client.app.state.mongo_db._cols["backtest_trades"].find_one = AsyncMock(return_value=None)
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days/2099-01-01/trades")
    assert resp.status_code == 404


# ── day status ────────────────────────────────────────────────────────────────


def test_get_day_status(client):
    client.app.state.mongo_db._cols["backtest_days"].find_one = AsyncMock(return_value={
        "run_id": "strangle_test1", "date": "2026-01-02",
        "status_log": ["09:15 spot=23000 score=+0.5 most_bull | flat | hold"],
    })
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days/2026-01-02/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status_log"] == ["09:15 spot=23000 score=+0.5 most_bull | flat | hold"]


def test_get_day_status_empty_log(client):
    client.app.state.mongo_db._cols["backtest_days"].find_one = AsyncMock(return_value={
        "run_id": "strangle_test1", "date": "2026-01-02",
    })
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days/2026-01-02/status")
    assert resp.status_code == 200
    assert resp.json()["status_log"] == []


def test_get_day_status_not_found(client):
    client.app.state.mongo_db._cols["backtest_days"].find_one = AsyncMock(return_value=None)
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/days/2099-01-01/status")
    assert resp.status_code == 404


# ── compare ───────────────────────────────────────────────────────────────────


def test_compare_runs(client):
    resp = client.post(
        "/api/v1/strangle-backtests/compare",
        json={"run_ids": ["strangle_test1"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert len(data["runs"]) == 1
    entry = data["runs"][0]
    assert entry["run_id"] == "strangle_test1"
    assert "equity" in entry


def test_compare_runs_too_many(client):
    resp = client.post(
        "/api/v1/strangle-backtests/compare",
        json={"run_ids": [f"run{i}" for i in range(11)]},
    )
    assert resp.status_code == 400


# ── launch ────────────────────────────────────────────────────────────────────


def test_launch_single_run(client):
    resp = client.post(
        "/api/v1/strangle-backtests/runs",
        json={
            "config": {"timeframe_min": 5, "lot_size": 65},
            "date_from": "2026-01-02",
            "date_to": "2026-01-10",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["type"] == "single"


def test_launch_walkforward(client):
    resp = client.post(
        "/api/v1/strangle-backtests/walkforwards",
        json={
            "config": {},
            "date_from": "2021-06-01",
            "date_to": "2026-05-31",
            "is_months": 12,
            "oos_months": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["type"] == "walkforward"


# ── promotion ─────────────────────────────────────────────────────────────────


def test_promote_non_pass_rejected(client):
    # run with verdict=REVIEW → should be rejected
    review_run = {**_RUN, "verdict": "REVIEW", "kind": "walkforward"}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=review_run)
    resp = client.post("/api/v1/strangle-backtests/runs/strangle_test1/promote")
    assert resp.status_code == 422


def test_promote_single_kind_rejected(client):
    # A single (non-walk-forward) run with a PASS verdict must still be rejected —
    # only walk-forward, out-of-sample-validated runs are promotable.
    single_pass_run = {**_RUN, "verdict": "PASS", "kind": "single"}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=single_pass_run)
    resp = client.post("/api/v1/strangle-backtests/runs/strangle_test1/promote")
    assert resp.status_code == 422
    assert "walkforward" in resp.json()["detail"]


def test_promote_pass_accepted(client, tmp_path, monkeypatch):
    pass_run = {**_RUN, "verdict": "PASS", "kind": "walkforward"}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=pass_run)

    monkeypatch.setattr(
        "pdp.strategy.promotion._STRATEGIES_DIR", tmp_path
    )
    import pdp.backtest.warehouse_routes as wr
    original = wr.asyncio.to_thread

    async def _sync_promote(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(wr.asyncio, "to_thread", _sync_promote)

    resp = client.post("/api/v1/strangle-backtests/runs/strangle_test1/promote")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategy_id" in data
    assert "yaml_path" in data

    # The evidence-snapshot doc is upserted (not blind-inserted) so re-promotion never duplicates.
    col_promotions = client.app.state.mongo_db._cols["backtest_promotions"]
    col_promotions.update_one.assert_awaited_once()
    (filt, update), kwargs = col_promotions.update_one.call_args
    assert filt == {"run_id": "strangle_test1"}
    assert update["$set"]["run_id"] == "strangle_test1"
    assert update["$set"]["verdict"] == "PASS"
    assert kwargs.get("upsert") is True


def test_promote_with_operator_note(client, tmp_path, monkeypatch):
    pass_run = {**_RUN, "verdict": "PASS", "kind": "walkforward",
                "stitched_oos": {"net": 50000.0, "profit_factor": 2.0, "sharpe": 1.0,
                                 "folds": 5, "positive_folds": 4}}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=pass_run)
    monkeypatch.setattr("pdp.strategy.promotion._STRATEGIES_DIR", tmp_path)
    import pdp.backtest.warehouse_routes as wr

    async def _sync_promote(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(wr.asyncio, "to_thread", _sync_promote)

    resp = client.post(
        "/api/v1/strangle-backtests/runs/strangle_test1/promote",
        json={"note": "reviewed OOS folds, looks solid"},
    )
    assert resp.status_code == 200
    col_promotions = client.app.state.mongo_db._cols["backtest_promotions"]
    (_, update), _ = col_promotions.update_one.call_args
    doc = update["$set"]
    assert doc["note"] == "reviewed OOS folds, looks solid"
    assert doc["verdict_breakdown"]["all_pass"] is True
    assert doc["stitched_oos"]["net"] == pytest.approx(50000.0)


def test_get_promotion_not_found(client):
    resp = client.get("/api/v1/strangle-backtests/runs/no_such_run/promotion")
    assert resp.status_code == 404


def test_get_promotion_found(client):
    promo_doc = {
        "run_id": "strangle_test1", "strategy_id": "promoted_strangle_test1",
        "verdict": "PASS", "note": None,
        "promoted_at": datetime.now(UTC),
    }
    client.app.state.mongo_db._cols["backtest_promotions"].find_one = AsyncMock(
        return_value=promo_doc
    )
    resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/promotion")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "strangle_test1"
    assert data["strategy_id"] == "promoted_strangle_test1"


# ── vs-paper ──────────────────────────────────────────────────────────────────


def _fake_pg_session(rows: list[tuple]) -> AsyncMock:
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture()
def _no_gap_radar(monkeypatch):
    """vs-paper cross-references the gap radar; stub it so tests don't hit a real Mongo/pymongo."""
    monkeypatch.setattr(
        "pdp.backtest.warehouse_routes.underlying_coverage",
        AsyncMock(return_value={"radar": {}}),
    )


def test_vs_paper_day_alignment(client, _no_gap_radar):
    rows = [
        ("directional_strangle_nifty", "1001", "SELL", 50, Decimal("100"), Decimal("5"),
         datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1001", "BUY", 50, Decimal("60"), Decimal("5"),
         datetime(2026, 1, 2, 6, 0, tzinfo=UTC)),
    ]
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session(rows)
    try:
        resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/vs-paper")
    finally:
        client.app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy_id"] == "directional_strangle_nifty"
    assert data["paper_data_available"] is True
    day = next(d for d in data["days"] if d["date"] == "2026-01-02")
    assert day["paper_net"] == pytest.approx(1990.0)
    assert day["backtest_net"] == 2000.0  # from _DAY fixture


def test_vs_paper_no_paper_data_returns_indicator_not_error(client, _no_gap_radar):
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/vs-paper")
    finally:
        client.app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["paper_data_available"] is False
    day = next(d for d in data["days"] if d["date"] == "2026-01-02")
    assert day["paper_net"] is None
    assert day["diverges"] is False


def test_vs_paper_run_not_found(client, _no_gap_radar):
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=None)
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get("/api/v1/strangle-backtests/runs/nope/vs-paper")
    finally:
        client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 404


def test_vs_paper_unresolvable_strategy_id(client, _no_gap_radar):
    # "strangle" family + no underlying deliberately defaults to NIFTY (canonical_id's
    # documented interim heuristic) — use a family with no live registry entry at all to
    # exercise the genuinely-unresolvable path.
    run = {**_RUN, "strategy_id": "no_such_family", "config": {}}
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=run)
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get("/api/v1/strangle-backtests/runs/strangle_test1/vs-paper")
    finally:
        client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 422


def test_vs_paper_minute_granularity_requires_date(client, _no_gap_radar):
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get(
            "/api/v1/strangle-backtests/runs/strangle_test1/vs-paper?granularity=minute"
        )
    finally:
        client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 400


def test_vs_paper_minute_diff_flags_mismatch(client, _no_gap_radar, monkeypatch):
    decision = {
        "run_id": "strangle_test1", "date": "2026-01-02",
        "ts_ist": datetime(2026, 1, 2, 9, 35), "event": "entry",
        "sub_reason": None, "action": "entry", "snapshot": {},
    }
    client.app.state.mongo_db._cols["backtest_decisions"].find.return_value = _cursor([decision])
    monkeypatch.setattr(
        "pdp.backtest.warehouse_routes.get_opensearch", lambda: object()
    )
    monkeypatch.setattr(
        "pdp.backtest.warehouse_routes.fetch_session_events",
        AsyncMock(return_value=[{
            "event_type": "bias_evaluated", "ist_time": "2026-01-02T09:35:00+05:30",
        }]),
    )
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get(
            "/api/v1/strangle-backtests/runs/strangle_test1/vs-paper"
            "?date=2026-01-02&granularity=minute"
        )
    finally:
        client.app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["granularity"] == "minute"
    assert len(data["minutes"]) == 1
    assert data["minutes"][0]["mismatch"] is True


# ── vs-paper/convergence (backtest-paper-parity task 6) ────────────────────────


def test_vs_paper_convergence_cumulative_sums(client, _no_gap_radar):
    days = [_DAY, {**_DAY, "date": "2026-01-03", "net": 1000.0}]
    client.app.state.mongo_db._cols["backtest_days"].find.return_value = _cursor(days)

    rows = [
        ("directional_strangle_nifty", "1001", "SELL", 50, Decimal("100"), Decimal("5"),
         datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1001", "BUY", 50, Decimal("60"), Decimal("5"),
         datetime(2026, 1, 2, 6, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1002", "SELL", 50, Decimal("50"), Decimal("5"),
         datetime(2026, 1, 3, 5, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1002", "BUY", 50, Decimal("50"), Decimal("5"),
         datetime(2026, 1, 3, 6, 0, tzinfo=UTC)),
    ]
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session(rows)
    try:
        resp = client.get(
            "/api/v1/strangle-backtests/runs/strangle_test1/vs-paper/convergence"
        )
    finally:
        client.app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["index"] == "NIFTY"
    assert data["aligned_days"] == 2
    assert data["backtest_cumulative_net"] == pytest.approx(3000.0)
    assert data["paper_cumulative_net"] == pytest.approx(1980.0)
    assert data["divergence"] == pytest.approx(
        data["backtest_cumulative_net"] - data["paper_cumulative_net"]
    )


def test_vs_paper_convergence_top_causes(client, monkeypatch):
    monkeypatch.setattr(
        "pdp.backtest.warehouse_routes.underlying_coverage",
        AsyncMock(return_value={"radar": {"2026-01-02": {"spot": "spot/VWAP missing"}}}),
    )
    rows = [
        ("directional_strangle_nifty", "1001", "SELL", 50, Decimal("100"), Decimal("5"),
         datetime(2026, 1, 2, 5, 0, tzinfo=UTC)),
        ("directional_strangle_nifty", "1001", "BUY", 50, Decimal("60"), Decimal("5"),
         datetime(2026, 1, 2, 6, 0, tzinfo=UTC)),
    ]
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session(rows)
    try:
        resp = client.get(
            "/api/v1/strangle-backtests/runs/strangle_test1/vs-paper/convergence"
        )
    finally:
        client.app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["diverging_days"] == 1
    assert data["top_causes"] == [{"cause": "spot/VWAP missing", "count": 1}]


def test_vs_paper_convergence_run_not_found(client, _no_gap_radar):
    client.app.state.mongo_db._cols["backtest_runs"].find_one = AsyncMock(return_value=None)
    client.app.dependency_overrides[get_db] = lambda: _fake_pg_session([])
    try:
        resp = client.get(
            "/api/v1/strangle-backtests/runs/nope/vs-paper/convergence"
        )
    finally:
        client.app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 404
