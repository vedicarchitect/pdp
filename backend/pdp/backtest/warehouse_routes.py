"""Mongo-backed read + launch + promote API for strangle backtest runs.

Prefix: /api/v1/strangle-backtests
Each route does exactly one thing (non-negotiable #3).

Read routes (tasks 2.2, 2.3, 2.4):
  GET  /runs                         list with filter/sort/pagination
  GET  /runs/{id}                    single run detail
  GET  /runs/{id}/equity             equity + drawdown series (from backtest_days)
  GET  /runs/{id}/days               per-day P&L table
  GET  /runs/{id}/folds              walk-forward folds (backtest_folds)
  GET  /runs/{id}/days/{date}/trades fill-level drill-down

Multi-run comparison (task 2.4):
  POST /compare                      aligned equity + headline metrics for N run ids

Launch (task 4.1):
  POST /runs                         submit single backtest job
  POST /sweeps                       submit sweep job
  POST /walkforwards                 submit walk-forward job

Promotion (task 5.2):
  POST /runs/{id}/promote            PASS-gated promotion to paper
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/strangle-backtests", tags=["Strangle Backtests"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _col(request: Request, name: str):
    return request.app.state.mongo_db[name]


def _doc_out(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip Mongo _id and stringify datetimes for JSON serialisation."""
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        from datetime import datetime
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


_SORT_FIELD_MAP = {
    "pf": "metrics.profit_factor",
    "net": "metrics.net",
    "max_dd": "metrics.max_dd",
    "sharpe": "metrics.sharpe",
    "calmar": "metrics.calmar",
    "win_rate": "metrics.win_rate",
    "created_at": "created_at",
}

_PASS_GATE_FIELDS = {"verdict": "PASS"}


# ── list + detail ─────────────────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(
    request: Request,
    kind: str | None = Query(None, description="Filter by kind: single, sweep, walkforward"),
    strategy_id: str | None = Query(None),
    verdict: str | None = Query(None, description="Filter by verdict: PASS, REVIEW"),
    sort_by: str = Query("created_at", description="Sort metric: pf, net, max_dd, sharpe, created_at"),
    sort_dir: int = Query(-1, description="-1 descending, 1 ascending"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List strangle backtest runs with optional filter + sort by headline metric."""
    filt: dict[str, Any] = {}
    if kind:
        filt["kind"] = kind
    if strategy_id:
        filt["strategy_id"] = strategy_id
    if verdict:
        filt["verdict"] = verdict.upper()

    sort_field = _SORT_FIELD_MAP.get(sort_by, "created_at")
    col = _col(request, "backtest_runs")
    cursor = col.find(filt, {"_id": 0}).sort(sort_field, sort_dir).skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await col.count_documents(filt)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [_doc_out(d) for d in docs],
    }


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> dict[str, Any]:
    """Return config, window, and headline metrics for a single run."""
    doc = await _col(request, "backtest_runs").find_one({"run_id": run_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(404, detail=f"Run not found: {run_id}")
    return _doc_out(doc)


@router.get("/runs/{run_id}/equity")
async def get_run_equity(request: Request, run_id: str) -> dict[str, Any]:
    """Return the equity and drawdown curve (date, cum_equity, peak, drawdown)."""
    cursor = _col(request, "backtest_days").find(
        {"run_id": run_id}, {"_id": 0, "date": 1, "net": 1, "cum_equity": 1, "peak": 1, "drawdown": 1}
    ).sort("date", 1)
    rows = await cursor.to_list(length=2000)
    if not rows:
        raise HTTPException(404, detail=f"No days found for run: {run_id}")
    return {"run_id": run_id, "equity": rows}


@router.get("/runs/{run_id}/days")
async def get_run_days(request: Request, run_id: str) -> dict[str, Any]:
    """Return the per-day P&L table."""
    cursor = _col(request, "backtest_days").find({"run_id": run_id}, {"_id": 0}).sort("date", 1)
    rows = await cursor.to_list(length=2000)
    if not rows:
        raise HTTPException(404, detail=f"No days found for run: {run_id}")
    return {"run_id": run_id, "days": rows}


@router.get("/runs/{run_id}/folds")
async def get_run_folds(request: Request, run_id: str) -> dict[str, Any]:
    """Return walk-forward folds (IS/OOS metrics + stitched-OOS summary + verdict)."""
    run = await _col(request, "backtest_runs").find_one(
        {"run_id": run_id}, {"_id": 0, "verdict": 1, "stitched_oos": 1})
    if run is None:
        raise HTTPException(404, detail=f"Run not found: {run_id}")

    cursor = _col(request, "backtest_folds").find({"run_id": run_id}, {"_id": 0}).sort("fold_index", 1)
    folds = await cursor.to_list(length=500)
    return {
        "run_id": run_id,
        "verdict": run.get("verdict"),
        "stitched_oos": run.get("stitched_oos"),
        "folds": folds,
    }


@router.get("/runs/{run_id}/days/{date}/trades")
async def get_day_trades(request: Request, run_id: str, date: str) -> dict[str, Any]:
    """Return fill-level detail for a single (run, date) bucket."""
    doc = await _col(request, "backtest_trades").find_one(
        {"run_id": run_id, "date": date}, {"_id": 0})
    if doc is None:
        raise HTTPException(404, detail=f"No trades found for run={run_id} date={date}")
    return doc


@router.get("/runs/{run_id}/days/{date}/status")
async def get_day_status(request: Request, run_id: str, date: str) -> dict[str, Any]:
    """Return the every-bar status trace (status_log) for a single (run, date)."""
    doc = await _col(request, "backtest_days").find_one(
        {"run_id": run_id, "date": date}, {"_id": 0, "status_log": 1})
    if doc is None:
        raise HTTPException(404, detail=f"Day {date} not found for run={run_id}")
    return {"run_id": run_id, "date": date, "status_log": doc.get("status_log") or []}


# ── comparison ────────────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    run_ids: list[str]


@router.post("/compare")
async def compare_runs(request: Request, body: CompareRequest) -> dict[str, Any]:
    """Return aligned equity + headline metrics for the requested run ids."""
    if not body.run_ids:
        raise HTTPException(400, detail="Provide at least one run_id.")
    if len(body.run_ids) > 10:
        raise HTTPException(400, detail="Compare supports up to 10 runs at a time.")

    runs_col = _col(request, "backtest_runs")
    days_col = _col(request, "backtest_days")

    result = []
    for rid in body.run_ids:
        run = await runs_col.find_one({"run_id": rid}, {"_id": 0})
        if run is None:
            result.append({"run_id": rid, "error": "not found"})
            continue
        cursor = days_col.find(
            {"run_id": rid}, {"_id": 0, "date": 1, "cum_equity": 1, "drawdown": 1}
        ).sort("date", 1)
        equity = await cursor.to_list(length=2000)
        result.append({
            "run_id": rid,
            "metrics": _doc_out(run).get("metrics", {}),
            "kind": run.get("kind"),
            "verdict": run.get("verdict"),
            "window": run.get("window", {}),
            "equity": equity,
        })
    return {"runs": result}


# ── launch ───────────────────────────────────────────────────────────────────

class SingleRunRequest(BaseModel):
    config: dict[str, Any]
    date_from: str
    date_to: str
    out_dir: str = "backtest/runs"
    hedge: bool | None = None
    mongo: bool = True


class SweepRequest(BaseModel):
    config: dict[str, Any]
    date_from: str
    date_to: str
    grid: dict[str, Any]  # e.g. {"st": "3,1;10,2", "tf": "5,15"}
    mongo: bool = True


class WalkForwardRequest(BaseModel):
    config: dict[str, Any]
    date_from: str
    date_to: str
    is_months: int = 12
    oos_months: int = 3
    step_months: int = 3
    objective: str = "sharpe"
    mongo: bool = True


@router.post("/runs")
async def launch_single_run(request: Request, body: SingleRunRequest) -> dict[str, Any]:
    """Submit a single backtest run as an async job; returns job id."""
    job_runner = request.app.state.job_runner
    job = await job_runner.submit(
        "backtest:single",
        {
            "config": body.config,
            "date_from": body.date_from,
            "date_to": body.date_to,
            "out_dir": body.out_dir,
            "hedge": body.hedge,
            "mongo": body.mongo,
        },
    )
    return {"job_id": str(job.id), "type": "single", "status": job.status}


@router.post("/sweeps")
async def launch_sweep(request: Request, body: SweepRequest) -> dict[str, Any]:
    """Submit a grid sweep as an async job; returns job id."""
    job_runner = request.app.state.job_runner
    job = await job_runner.submit(
        "backtest:sweep",
        {
            "config": body.config,
            "date_from": body.date_from,
            "date_to": body.date_to,
            "grid": body.grid,
            "mongo": body.mongo,
        },
    )
    return {"job_id": str(job.id), "type": "sweep", "status": job.status}


@router.post("/walkforwards")
async def launch_walkforward(request: Request, body: WalkForwardRequest) -> dict[str, Any]:
    """Submit a walk-forward optimization as an async job; returns job id."""
    job_runner = request.app.state.job_runner
    job = await job_runner.submit(
        "backtest:walkforward",
        {
            "config": body.config,
            "date_from": body.date_from,
            "date_to": body.date_to,
            "is_months": body.is_months,
            "oos_months": body.oos_months,
            "step_months": body.step_months,
            "objective": body.objective,
            "mongo": body.mongo,
        },
    )
    return {"job_id": str(job.id), "type": "walkforward", "status": job.status}


# ── promotion ─────────────────────────────────────────────────────────────────

@router.post("/runs/{run_id}/promote")
async def promote_run(request: Request, run_id: str) -> dict[str, Any]:
    """Promote a PASS walk-forward run to a paper strategy.

    Rejects non-PASS runs. On success: writes strategies/<id>.yaml (paper-first),
    records a promotion document, and flips promotion_state.
    """
    run = await _col(request, "backtest_runs").find_one({"run_id": run_id}, {"_id": 0})
    if run is None:
        raise HTTPException(404, detail=f"Run not found: {run_id}")

    from pdp.strategy.promotion import promote_run as _promote
    result = await asyncio.to_thread(_promote, run)
    if "error" in result:
        raise HTTPException(422, detail=result["error"])

    # Update promotion_state in Mongo
    await _col(request, "backtest_runs").update_one(
        {"run_id": run_id},
        {"$set": {"promotion_state": "promoted"}},
    )
    # Record promotion audit doc
    from datetime import UTC, datetime
    await _col(request, "backtest_promotions").insert_one({
        "run_id": run_id,
        "verdict": run.get("verdict"),
        "config": run.get("config", {}),
        "strategy_id": result["strategy_id"],
        "yaml_path": result["yaml_path"],
        "promoted_at": datetime.now(UTC),
    })
    return result
