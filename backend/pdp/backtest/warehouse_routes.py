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
  GET  /sweeps/{sweep_id}            sweep leaderboard (ranked combos + best_param)
  GET  /runs/{id}/decisions          decision trace (events by default; ?full=true for per-minute)
  GET  /runs/{id}/promotion          promotion rationale/evidence
  GET  /runs/{id}/vs-paper           backtest-vs-paper alignment (per-day; ?date=&granularity=minute)
  GET  /runs/{id}/vs-paper/convergence  cumulative divergence + top causes (backtest-paper-parity)

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
from collections import Counter
from datetime import date as _date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.backtest.paper_compare import (
    align_days,
    annotate_day_divergence,
    annotate_minute_divergence,
    minute_diff,
    paper_pnl_by_strategy,
    resolve_live_strategy_id,
)
from pdp.db.session import get_db
from pdp.observability.client import get_opensearch
from pdp.observability.query import fetch_session_events
from pdp.settings import get_settings
from pdp.warehouse.coverage import underlying_coverage

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


@router.get("/runs/{run_id}/decisions")
async def get_run_decisions(
    request: Request,
    run_id: str,
    date: str | None = Query(None, description="Restrict to one trade date YYYY-MM-DD"),
    full: bool = Query(False, description="Replay the full per-minute trace for `date` (requires date)"),
) -> dict[str, Any]:
    """Return the why-entry/why-exit decision trace for a run.

    Default: the persisted reason-coded `backtest_decisions` events (optionally
    filtered to one date). With ``full=true`` (requires ``date``): re-materializes the
    every-minute status trace for that single day by deterministic replay — not stored.
    """
    if full:
        if not date:
            raise HTTPException(400, detail="`date` is required when full=true")
        run = await _col(request, "backtest_runs").find_one(
            {"run_id": run_id}, {"_id": 0, "config": 1, "strategy_id": 1, "window": 1})
        if run is None:
            raise HTTPException(404, detail=f"Run not found: {run_id}")
        underlying = (run.get("config") or {}).get("underlying", "NIFTY")
        from pdp.backtest.replay import replay_day
        result = await asyncio.to_thread(replay_day, run.get("config") or {}, underlying, date)
        if not result["found"]:
            raise HTTPException(404, detail=f"No decision-bar data for run={run_id} date={date}")
        return {"run_id": run_id, "date": date, "full": True, **result}

    filt: dict[str, Any] = {"run_id": run_id}
    if date:
        filt["date"] = date
    cursor = _col(request, "backtest_decisions").find(filt, {"_id": 0}).sort("ts_ist", 1)
    docs = await cursor.to_list(length=5000)
    for d in docs:
        ts = d.get("ts_ist")
        if hasattr(ts, "isoformat"):
            d["ts_ist"] = ts.isoformat()
    return {"run_id": run_id, "date": date, "full": False, "decisions": docs}


@router.get("/sweeps/{sweep_id}")
async def get_sweep(request: Request, sweep_id: str) -> dict[str, Any]:
    """Return a sweep's ranked leaderboard (combos + best_param)."""
    doc = await _col(request, "backtest_sweeps").find_one({"sweep_id": sweep_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(404, detail=f"Sweep not found: {sweep_id}")
    return _doc_out(doc)


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
    out_dir: str | None = None  # None = DB-first (default); set to also archive local files
    hedge: bool | None = None
    mongo: bool = True


class SweepRequest(BaseModel):
    config: dict[str, Any]
    date_from: str
    date_to: str
    grid: dict[str, list[Any]]  # e.g. {"hedge_enabled": [true, false], "day_loss_limit": [10000, 15000]}
    objective: str = "pf"
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
            "objective": body.objective,
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


class PromoteRequest(BaseModel):
    note: str | None = None


# ── promotion ─────────────────────────────────────────────────────────────────

@router.post("/runs/{run_id}/promote")
async def promote_run(request: Request, run_id: str, body: PromoteRequest | None = None) -> dict[str, Any]:
    """Promote a PASS walk-forward run to a paper strategy.

    Rejects non-PASS runs. On success: writes strategies/<id>.yaml (paper-first),
    records a self-contained promotion evidence doc (stitched-OOS metrics, per-threshold
    PASS-vs-actual breakdown, positive-fold fraction, source-run link, optional operator
    note), and flips promotion_state.
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
    # Record self-contained promotion evidence doc + dual-sink to OpenSearch
    from pdp.backtest.store import build_promotion_doc, ship_promotion_event
    promotion_doc = build_promotion_doc(run, result, note=body.note if body else None)
    await _col(request, "backtest_promotions").update_one(
        {"run_id": run_id},
        {"$set": promotion_doc},
        upsert=True,
    )
    ship_promotion_event(promotion_doc)
    return result


@router.get("/runs/{run_id}/promotion")
async def get_promotion(request: Request, run_id: str) -> dict[str, Any]:
    """Return the promotion rationale/evidence for a run, if it has been promoted."""
    doc = await _col(request, "backtest_promotions").find_one({"run_id": run_id}, {"_id": 0})
    if doc is None:
        raise HTTPException(404, detail=f"No promotion recorded for run: {run_id}")
    return _doc_out(doc)


# ── backtest-vs-paper comparison ────────────────────────────────────────────────

async def _gap_radar(
    request: Request, underlying: str, win_from: _date, win_to: _date,
) -> dict[str, Any] | None:
    """Best-effort gap-radar lookup for divergence root-causing; `None` if unavailable."""
    try:
        coverage = await underlying_coverage(
            request.app.state.mongo_db, get_settings(), underlying,
            window_from=win_from, window_to=win_to,
        )
    except ValueError:
        return None
    return coverage.get("radar")


@router.get("/runs/{run_id}/vs-paper")
async def get_run_vs_paper(
    request: Request,
    run_id: str,
    date: str | None = Query(
        None, description="Restrict to one trade date YYYY-MM-DD (required when granularity=minute)"),
    granularity: str = Query(
        "day", description="'day' (default, per-day P&L alignment) or 'minute' (decision diff for `date`)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Align a backtest run against the live paper results for the same strategy.

    Default (`granularity=day`): per-day backtest-vs-paper net P&L, aligned by date, with
    divergence annotated against the data-coverage gap radar. `granularity=minute` (requires
    `date`): a minute-level decision-event diff between the run's `backtest_decisions` trace
    and the live strangle event log, normalized onto a shared vocabulary.
    """
    run = await _col(request, "backtest_runs").find_one(
        {"run_id": run_id}, {"_id": 0, "config": 1, "window": 1})
    if run is None:
        raise HTTPException(404, detail=f"Run not found: {run_id}")

    live_strategy_id = resolve_live_strategy_id(run)
    if live_strategy_id is None:
        raise HTTPException(422, detail=f"Cannot resolve a live strategy_id for run: {run_id}")

    window = run.get("window") or {}
    if not window.get("from") or not window.get("to"):
        raise HTTPException(422, detail=f"Run {run_id} has no window to compare against.")
    win_from = _date.fromisoformat(str(window["from"])[:10])
    win_to = _date.fromisoformat(str(window["to"])[:10])
    underlying = str((run.get("config") or {}).get("underlying", "NIFTY"))

    if granularity == "minute":
        if not date:
            raise HTTPException(400, detail="`date` is required when granularity=minute")
        decisions = await _col(request, "backtest_decisions").find(
            {"run_id": run_id, "date": date}, {"_id": 0}).sort("ts_ist", 1).to_list(length=5000)

        live_docs: list[dict[str, Any]] = []
        client = get_opensearch()
        if client is not None:
            live_docs = await fetch_session_events(client, date=date, strategy_id=live_strategy_id)

        rows = minute_diff(decisions, live_docs)
        radar = await _gap_radar(request, underlying, win_from, win_to)
        rows = annotate_minute_divergence(rows, radar)
        return {
            "run_id": run_id,
            "strategy_id": live_strategy_id,
            "date": date,
            "granularity": "minute",
            "minutes": rows,
        }

    backtest_days = await _col(request, "backtest_days").find(
        {"run_id": run_id}, {"_id": 0, "date": 1, "net": 1}).sort("date", 1).to_list(length=2000)

    paper_by_strategy = await paper_pnl_by_strategy(db, win_from, win_to, live_strategy_id)
    paper_days = paper_by_strategy.get(live_strategy_id, [])

    aligned = align_days(backtest_days, paper_days)
    radar = await _gap_radar(request, underlying, win_from, win_to)
    aligned = annotate_day_divergence(aligned, radar)

    return {
        "run_id": run_id,
        "strategy_id": live_strategy_id,
        "granularity": "day",
        "paper_data_available": bool(paper_days),
        "days": aligned,
    }


@router.get("/runs/{run_id}/vs-paper/convergence")
async def get_run_vs_paper_convergence(
    request: Request,
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cumulative backtest-vs-paper convergence for a run's index (daily convergence check).

    Tracks whether paper is walking toward the run's proven trajectory as paper accumulates:
    cumulative net on each side plus the most frequent divergence causes, computed from the
    same per-day alignment rows as ``/vs-paper`` (no new store). A day only counts toward the
    cumulative totals once both sides have traded it (see `align_days`).
    """
    run = await _col(request, "backtest_runs").find_one(
        {"run_id": run_id}, {"_id": 0, "config": 1, "window": 1})
    if run is None:
        raise HTTPException(404, detail=f"Run not found: {run_id}")

    live_strategy_id = resolve_live_strategy_id(run)
    if live_strategy_id is None:
        raise HTTPException(422, detail=f"Cannot resolve a live strategy_id for run: {run_id}")

    window = run.get("window") or {}
    if not window.get("from") or not window.get("to"):
        raise HTTPException(422, detail=f"Run {run_id} has no window to compare against.")
    win_from = _date.fromisoformat(str(window["from"])[:10])
    win_to = _date.fromisoformat(str(window["to"])[:10])
    underlying = str((run.get("config") or {}).get("underlying", "NIFTY"))

    backtest_days = await _col(request, "backtest_days").find(
        {"run_id": run_id}, {"_id": 0, "date": 1, "net": 1}).sort("date", 1).to_list(length=2000)

    paper_by_strategy = await paper_pnl_by_strategy(db, win_from, win_to, live_strategy_id)
    paper_days = paper_by_strategy.get(live_strategy_id, [])

    aligned = align_days(backtest_days, paper_days)
    radar = await _gap_radar(request, underlying, win_from, win_to)
    aligned = annotate_day_divergence(aligned, radar)

    backtest_cumulative_net = round(
        sum(d["backtest_net"] for d in aligned if d["backtest_net"] is not None), 2)
    paper_cumulative_net = round(
        sum(d["paper_net"] for d in aligned if d["paper_net"] is not None), 2)
    divergence = round(backtest_cumulative_net - paper_cumulative_net, 2)

    cause_counts: Counter[str] = Counter(
        d["cause"] for d in aligned if d.get("diverges") and d.get("cause")
    )
    top_causes = [{"cause": cause, "count": count} for cause, count in cause_counts.most_common(5)]

    return {
        "run_id": run_id,
        "strategy_id": live_strategy_id,
        "index": underlying,
        "paper_data_available": bool(paper_days),
        "aligned_days": len(aligned),
        "diverging_days": sum(1 for d in aligned if d.get("diverges")),
        "backtest_cumulative_net": backtest_cumulative_net,
        "paper_cumulative_net": paper_cumulative_net,
        "divergence": divergence,
        "top_causes": top_causes,
    }
