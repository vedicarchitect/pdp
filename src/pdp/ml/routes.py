from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from pdp.jobs.runner import JobRunner
from pdp.ml.registry import get_active_model_version, list_artifacts, set_active_model

router = APIRouter()


async def train_handler(
    job_id: UUID,
    params: dict[str, Any],
    progress_cb,
) -> dict[str, Any]:
    from pdp.ml.train import train

    loop = asyncio.get_running_loop()

    def sync_progress(pct: int, msg: str) -> None:
        asyncio.run_coroutine_threadsafe(progress_cb(job_id, pct, msg), loop)

    def _do_train() -> str:
        return train(
            security_id=params.get("security_id", "13"),
            timeframe=params.get("timeframe", "15m"),
            days=params.get("days", 90),
            version=params.get("version"),
            head=params.get("head", "directional"),
            progress_cb=sync_progress,
        )

    result_version: str = await asyncio.to_thread(_do_train)
    return {"version": result_version}


@router.post("/train")
async def trigger_training(params: dict[str, Any], request: Request):
    runner: JobRunner = request.app.state.job_runner
    job = await runner.submit("ml_train", params)
    return {"job_id": str(job.id), "status": job.status}


@router.get("/models")
async def get_models():
    from pdp.settings import get_settings

    settings = get_settings()
    # list_artifacts and get_active_model_version do blocking filesystem I/O
    active_ver = await asyncio.to_thread(get_active_model_version, settings.ML_MODEL_DIR)
    artifacts = await asyncio.to_thread(list_artifacts, settings.ML_MODEL_DIR)

    models = []
    for meta, report in artifacts:
        m = meta.to_dict()
        m["is_active"] = meta.version == active_ver
        m["report"] = report
        models.append(m)
    return {"models": models}


@router.post("/deploy/{version}")
async def deploy_model(version: str):
    from pdp.settings import get_settings

    settings = get_settings()
    artifacts = await asyncio.to_thread(list_artifacts, settings.ML_MODEL_DIR)
    if not any(a[0].version == version for a in artifacts):
        raise HTTPException(status_code=404, detail="Version not found")
    await asyncio.to_thread(set_active_model, settings.ML_MODEL_DIR, version)
    return {"status": "deployed", "version": version}
