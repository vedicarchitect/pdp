from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from uuid import UUID

from pdp.db.session import get_session_maker
from pdp.jobs.models import Job, JobStatus

log = structlog.get_logger()
router = APIRouter()


@router.websocket("/{job_id}")
async def job_websocket(websocket: WebSocket, job_id: UUID):
    await websocket.accept()
    redis = websocket.app.state.redis
    pubsub = redis.pubsub()
    channel = f"job:{job_id}:progress"

    try:
        # Subscribe BEFORE checking current DB state — closes the race window where
        # the job finishes between HTTP response and WS connect.
        await pubsub.subscribe(channel)

        async with get_session_maker()() as db:
            job = await db.get(Job, job_id)

        if job and job.status in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ):
            # Job already finished before we subscribed; synthesise terminal message.
            msg = (
                "Completed"
                if job.status == JobStatus.COMPLETED.value
                else "Cancelled"
                if job.status == JobStatus.CANCELLED.value
                else f"Failed: {job.error or 'unknown'}"
            )
            await websocket.send_text(
                json.dumps({"progress": job.progress or 0, "message": msg})
            )
            return

        log.info("job_ws_connected", job_id=str(job_id))

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                # decode_responses=True on the Redis client means data is already str
                data: str = message["data"]
                await websocket.send_text(data)
                payload = json.loads(data)
                msg_text = str(payload.get("message", ""))
                if msg_text in ("Completed", "Cancelled") or msg_text.startswith("Failed:"):
                    break
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        log.info("job_ws_disconnected", job_id=str(job_id))
    except Exception as e:
        log.error("job_ws_error", job_id=str(job_id), error=str(e))
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        try:
            await websocket.close()
        except Exception:
            pass
