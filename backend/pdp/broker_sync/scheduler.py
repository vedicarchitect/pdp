"""EOD scheduler for broker sync.

A lightweight asyncio loop that fires the daily sync once per day at ``BROKER_SYNC_EOD_TIME``
(IST, default 15:45), after market close. Idempotent: it skips if today already completed
``ok``. Kept separate from the API so the app stays stateless (cloud-readiness constraint).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from pdp.broker_sync.models import SyncTrigger
from pdp.broker_sync.service import BrokerSyncService

log = structlog.get_logger()

_IST = timezone(timedelta(hours=5, minutes=30))


class BrokerSyncScheduler:
    def __init__(self, service: BrokerSyncService, eod_time: str = "15:45") -> None:
        self._service = service
        try:
            hh, mm = eod_time.split(":")
            self._target = (int(hh), int(mm))
        except (ValueError, AttributeError):
            self._target = (15, 45)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="broker-sync-eod")
        log.info(
            "broker_sync_scheduler_started",
            eod_time=f"{self._target[0]:02d}:{self._target[1]:02d}",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now(_IST)
                date_str = now.strftime("%Y-%m-%d")
                past_target = (now.hour, now.minute) >= self._target
                if past_target and not await self._service.already_succeeded(date_str):
                    log.info("broker_sync_eod_fire", snapshot_date=date_str)
                    await self._service.run_daily(date_str, trigger=SyncTrigger.AUTO)
            except Exception as exc:
                log.warning("broker_sync_scheduler_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                pass
