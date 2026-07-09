from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from pdp.jobs.models import Job, JobStatus
from pdp.jobs.runner import JobRunner

pytestmark = pytest.mark.asyncio


async def dummy_handler(job_id: UUID, params: dict[str, Any], progress_cb) -> dict[str, Any]:
    await progress_cb(job_id, 10, "started")
    await asyncio.sleep(0.1)
    if params.get("should_fail"):
        raise RuntimeError("simulated failure")
    await progress_cb(job_id, 90, "almost done")
    return {"status": "ok"}


async def long_handler(job_id: UUID, params: dict[str, Any], progress_cb) -> dict[str, Any]:
    await progress_cb(job_id, 10, "started")
    await asyncio.sleep(10.0)
    return {"status": "ok"}


@pytest.fixture
def redis_client():
    mock = AsyncMock()
    return mock


@pytest.fixture
def db_session_factory():
    from pdp.db.session import get_session_maker

    return get_session_maker()


@pytest.fixture
def test_runner(db_session_factory, redis_client):
    runner = JobRunner(db_session_factory, redis_client)
    runner.register_handler("test:dummy", dummy_handler)
    runner.register_handler("test:long", long_handler)
    return runner


async def _await_task(runner: JobRunner, job_id: UUID) -> None:
    task = runner._tasks.get(job_id)
    if task:
        try:
            await task
        except BaseException:
            pass


# 8.2 — PENDING → RUNNING → COMPLETED
async def test_job_success(test_runner, db_session_factory, redis_client):
    job = await test_runner.submit("test:dummy", {"should_fail": False})
    await _await_task(test_runner, job.id)

    async with db_session_factory() as db:
        j = await db.get(Job, job.id)
        assert j.status == JobStatus.COMPLETED.value
        assert j.result == {"status": "ok"}
        assert j.progress == 100

    assert redis_client.publish.call_count >= 2


# 8.4 — RUNNING → FAILED with error message
async def test_job_failure(test_runner, db_session_factory):
    job = await test_runner.submit("test:dummy", {"should_fail": True})
    await _await_task(test_runner, job.id)

    async with db_session_factory() as db:
        j = await db.get(Job, job.id)
        assert j.status == JobStatus.FAILED.value
        assert "simulated failure" in j.error


# 8.3 — RUNNING → CANCELLED
async def test_job_cancel(test_runner, db_session_factory):
    job = await test_runner.submit("test:long", {})
    await asyncio.sleep(0.05)  # let it reach RUNNING

    async with db_session_factory() as db:
        j = await db.get(Job, job.id)
        assert j.status == JobStatus.RUNNING.value

    cancelled = await test_runner.cancel(job.id)
    assert cancelled is True

    await _await_task(test_runner, job.id)

    async with db_session_factory() as db:
        j = await db.get(Job, job.id)
        assert j.status == JobStatus.CANCELLED.value


# 8.5 — destructive operation gating: unknown job type raises ValueError (not submitted)
async def test_unknown_job_type_rejected(test_runner):
    with pytest.raises(ValueError, match="Unknown job type"):
        await test_runner.submit("housekeeping:reset-paper", {})


# 8.5b — reset-paper handler rejects missing confirm flag
async def test_reset_paper_requires_confirm(db_session_factory, redis_client):
    from pdp.housekeeping.tasks import reset_paper

    runner = JobRunner(db_session_factory, redis_client)
    runner.register_handler("housekeeping:reset-paper", reset_paper)

    job = await runner.submit("housekeeping:reset-paper", {"confirm": False})
    await _await_task(runner, job.id)

    async with db_session_factory() as db:
        j = await db.get(Job, job.id)
        assert j.status == JobStatus.FAILED.value
        assert "confirm" in j.error.lower()
