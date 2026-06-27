from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from uuid import UUID

import structlog

from pdp.jobs.models import Job, JobStatus

log = structlog.get_logger()

JobHandler = Callable[[UUID, dict[str, Any], Callable[[UUID, int, str], Awaitable[None]]], Awaitable[Any]]


class JobRunner:
    def __init__(self, db_session_factory, redis_client):
        self._db_session_factory = db_session_factory
        self._redis = redis_client
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._handlers: dict[str, JobHandler] = {}

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def submit(self, job_type: str, params: dict[str, Any]) -> Job:
        if job_type not in self._handlers:
            raise ValueError(f"Unknown job type: {job_type}")

        job = Job(type=job_type, params=params, status=JobStatus.PENDING.value)
        async with self._db_session_factory() as db:
            db.add(job)
            await db.commit()
            await db.refresh(job)
            db.expunge(job)

        task = asyncio.create_task(self._execute(job))
        self._tasks[job.id] = task
        return job

    async def _on_progress(self, job_id: UUID, progress: int, message: str) -> None:
        payload = json.dumps({"progress": progress, "message": message})
        await self._redis.publish(f"job:{job_id}:progress", payload)
        # Persist at 10% boundaries; skip 0 to avoid overwriting non-zero progress on cancel/fail
        if progress > 0 and progress % 10 == 0:
            async with self._db_session_factory() as db:
                j = await db.get(Job, job_id)
                if j:
                    j.progress = progress
                    j.progress_message = message
                    await db.commit()

    async def _execute(self, job: Job) -> None:
        job_id = job.id
        _current_progress = 0

        async def _tracked(jid: UUID, progress: int, message: str) -> None:
            nonlocal _current_progress
            _current_progress = progress
            await self._on_progress(jid, progress, message)

        try:
            async with self._db_session_factory() as db:
                j = await db.get(Job, job_id)
                if j is None:
                    log.error("job_missing_on_start", job_id=str(job_id))
                    return
                j.status = JobStatus.RUNNING.value
                j.started_at = datetime.now(UTC)
                await db.commit()

            handler = self._handlers[job.type]
            log.info("job_started", job_id=str(job_id), type=job.type)

            result = await handler(job_id, job.params, _tracked)

            async with self._db_session_factory() as db:
                j = await db.get(Job, job_id)
                if j is None:
                    log.error("job_missing_on_complete", job_id=str(job_id))
                    return
                j.status = JobStatus.COMPLETED.value
                j.progress = 100
                j.result = result
                j.completed_at = datetime.now(UTC)
                await db.commit()

            # Publish terminal message after DB commit (no extra DB round-trip via _on_progress)
            await self._redis.publish(
                f"job:{job_id}:progress",
                json.dumps({"progress": 100, "message": "Completed"}),
            )
            log.info("job_completed", job_id=str(job_id), type=job.type)

        except asyncio.CancelledError:
            async with self._db_session_factory() as db:
                j = await db.get(Job, job_id)
                if j is not None:
                    j.status = JobStatus.CANCELLED.value
                    j.completed_at = datetime.now(UTC)
                    await db.commit()
            await self._redis.publish(
                f"job:{job_id}:progress",
                json.dumps({"progress": _current_progress, "message": "Cancelled"}),
            )
            log.info("job_cancelled", job_id=str(job_id))
            raise

        except Exception as e:
            import traceback

            async with self._db_session_factory() as db:
                j = await db.get(Job, job_id)
                if j is not None:
                    j.status = JobStatus.FAILED.value
                    j.error = str(e)
                    j.logs = traceback.format_exc()
                    j.completed_at = datetime.now(UTC)
                    await db.commit()
            await self._redis.publish(
                f"job:{job_id}:progress",
                json.dumps({"progress": _current_progress, "message": f"Failed: {e}"}),
            )
            log.error("job_failed", job_id=str(job_id), error=str(e), exc_info=True)

        finally:
            self._tasks.pop(job_id, None)

    async def cancel(self, job_id: UUID) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False
