from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db
from pdp.jobs.models import Job
from pdp.jobs.runner import JobRunner

router = APIRouter()


@router.get("")
async def list_jobs(
    status: str | None = None,
    type: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    # WHERE before LIMIT — filters applied first, then cap
    stmt = select(Job).order_by(desc(Job.created_at))
    if status:
        stmt = stmt.where(Job.status == status)
    if type:
        stmt = stmt.where(Job.type == type)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return {"jobs": [j.to_dict() for j in jobs]}


@router.get("/{job_id}")
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: UUID, request: Request):
    runner: JobRunner = request.app.state.job_runner
    cancelled = await runner.cancel(job_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled (not running)")
    return {"status": "cancelled"}


@router.delete("/{job_id}")
async def delete_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("PENDING", "RUNNING"):
        raise HTTPException(status_code=400, detail="Cannot delete a running job")
    await db.delete(job)
    await db.commit()
    return {"status": "deleted"}
