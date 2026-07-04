"""Async job handlers for backtest:single, backtest:sweep, backtest:walkforward.

Each handler is registered with the JobRunner and runs the backtest in a subprocess so
the event loop is not blocked. On completion the run folder is ingested into Mongo when
`mongo` is set in the params.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

import structlog

log = structlog.get_logger()

# backend/pdp/backtest/job_handlers.py -> backend/ (cwd for backtest/*.py script invocations)
_REPO_ROOT = Path(__file__).parent.parent.parent


async def _run_subprocess(
    cmd: list[str],
    progress_cb: Callable[[UUID, int, str], Awaitable[None]],
    job_id: UUID,
) -> int:
    """Run a subprocess and stream stdout lines as progress messages."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(_REPO_ROOT),
    )
    lines: list[str] = []
    pct = 5
    if proc.stdout:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            lines.append(line)
            await progress_cb(job_id, pct, line[:200])
            pct = min(pct + 1, 95)
    rc = await proc.wait()
    return rc


async def backtest_single_handler(
    job_id: UUID,
    params: dict[str, Any],
    progress: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    """Run a single strangle backtest and optionally ingest to Mongo."""
    import json
    import tempfile

    await progress(job_id, 2, "preparing config")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        # Write config as YAML using the StrangleConfig serializer
        from pdp.backtest.strangle_config import StrangleConfig  # noqa: PLC0415
        cfg = StrangleConfig.from_dict(params.get("config", {}))
        tf.write(cfg.to_yaml())
        cfg_path = tf.name

    cmd = [
        sys.executable, "backtest/strangle_run.py",
        "--config-file", cfg_path,
        "--from", params["date_from"],
        "--to", params["date_to"],
    ]
    if params.get("out_dir"):
        cmd += ["--out-dir", params["out_dir"]]
    if params.get("hedge") is True:
        cmd.append("--hedge")
    elif params.get("hedge") is False:
        cmd.append("--no-hedge")
    if params.get("mongo", True) is False:
        cmd.append("--no-mongo")

    await progress(job_id, 5, "running backtest")
    rc = await _run_subprocess(cmd, progress, job_id)
    if rc != 0:
        raise RuntimeError(f"backtest process exited with code {rc}")

    await progress(job_id, 99, "complete")
    return {"status": "complete", "kind": "single"}


async def backtest_sweep_handler(
    job_id: UUID,
    params: dict[str, Any],
    progress: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    """Run a real in-process strangle parameter sweep and persist a ranked leaderboard.

    Loads the market window once (in a worker thread, off the event loop) and replays
    every grid combination through ``simulate_strangle_day`` via ``sweep_engine``, then
    ranks and upserts the leaderboard to ``backtest_sweeps`` (dual-sunk to OpenSearch).
    """
    import uuid as uuid_lib

    from pdp.backtest.sweep_engine import run_strangle_sweep
    from pdp.backtest.store import BacktestStore, build_sweep_doc

    grid = params.get("grid") or {}
    if not grid:
        raise ValueError("sweep grid must have at least one field, e.g. {'hedge_enabled': [true, false]}")

    loop = asyncio.get_running_loop()

    def on_progress(pct: int, msg: str) -> None:
        asyncio.run_coroutine_threadsafe(progress(job_id, pct, msg), loop)

    await progress(job_id, 2, "preparing sweep")
    result = await asyncio.to_thread(
        run_strangle_sweep,
        date_from=params["date_from"],
        date_to=params["date_to"],
        base_config=params.get("config", {}),
        grid=grid,
        no_commission=bool(params.get("no_commission", False)),
        on_progress=on_progress,
    )

    sweep_id = params.get("sweep_id") or f"sweep_{uuid_lib.uuid4().hex[:12]}"
    doc = build_sweep_doc(
        sweep_id,
        kind="sweep",
        window=result["window"],
        grid=grid,
        objective=params.get("objective", "pf"),
        combos=result["combos"],
        base_config=params.get("config", {}),
    )

    if params.get("mongo", True):
        from pdp.settings import get_settings
        from pymongo import MongoClient

        s = get_settings()
        mc = MongoClient(s.MONGO_URI)
        db = mc[s.MONGO_DB_NAME]
        store = BacktestStore(
            db["backtest_runs"], db["backtest_days"], db["backtest_folds"], db["backtest_trades"],
            col_sweeps=db["backtest_sweeps"], col_decisions=db["backtest_decisions"],
        )
        await asyncio.to_thread(store.upsert_sweep, doc)

    await progress(job_id, 99, f"sweep complete: {result['n_combos']} combos")
    return {
        "status": "complete", "kind": "sweep", "sweep_id": sweep_id,
        "n_combos": result["n_combos"], "best_param": doc["best_param"],
    }


async def backtest_walkforward_handler(
    job_id: UUID,
    params: dict[str, Any],
    progress: Callable[[UUID, int, str], Awaitable[None]],
) -> dict[str, Any]:
    """Run a walk-forward optimization job."""
    await progress(job_id, 2, "preparing walk-forward")

    cmd = [
        sys.executable, "backtest/strangle_walkforward.py",
        "--from", params["date_from"],
        "--to", params["date_to"],
        "--is-months", str(params.get("is_months", 12)),
        "--oos-months", str(params.get("oos_months", 3)),
        "--step-months", str(params.get("step_months", 3)),
        "--objective", params.get("objective", "sharpe"),
    ]
    if params.get("out_csv"):
        cmd += ["--out", params["out_csv"]]
    if params.get("mongo", True) is False:
        cmd.append("--no-mongo")

    await progress(job_id, 5, "running walk-forward")
    rc = await _run_subprocess(cmd, progress, job_id)
    if rc != 0:
        raise RuntimeError(f"walk-forward process exited with code {rc}")

    return {"status": "complete", "kind": "walkforward"}
