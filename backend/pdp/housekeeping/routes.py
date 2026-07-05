from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pdp.jobs.runner import JobRunner

router = APIRouter()

_VALID_TASKS = {
    "backfill-spot",
    "backfill-options",
    "backfill-levels",
    "backfill-vix",
    "reset-paper",
    "validate-warehouse",
    "snapshot-instruments",
}


@router.post("/{task_name}")
async def run_housekeeping_task(task_name: str, params: dict[str, Any], request: Request):
    if task_name not in _VALID_TASKS:
        raise HTTPException(status_code=404, detail=f"Task '{task_name}' not found")

    if task_name == "reset-paper" and not params.get("confirm"):
        raise HTTPException(
            status_code=400,
            detail="This operation will delete all paper orders, trades, and positions. Include confirm: true to proceed.",
        )

    runner: JobRunner = request.app.state.job_runner
    job = await runner.submit(f"housekeeping:{task_name}", params)
    return {"job_id": str(job.id), "status": job.status}
