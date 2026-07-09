"""Intraday broker account poller.

A market-hours loop that refreshes the broker account state (holdings, positions,
funds) periodically. This ensures that the platform's view of the broker's
holdings and funds is fresh throughout the day, and positions stay in sync.

Paper-safe: skips gracefully if credentials are not configured.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import structlog

from pdp.broker_sync.service import BrokerSyncService
from pdp.settings import Settings

log = structlog.get_logger()
_IST = ZoneInfo("Asia/Kolkata")


class BrokerIntradayPoller:
    def __init__(self, service: BrokerSyncService, settings: Settings) -> None:
        self._service = service
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self._settings.BROKER_SYNC_ENABLED:
            return
        self._task = asyncio.create_task(self._loop(), name="broker-intraday-poller")
        log.info(
            "broker_intraday_poller_started",
            interval_sec=self._settings.BROKER_INTRADAY_POLL_SECONDS,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _is_market_hours(self) -> bool:
        now_ist = datetime.now(_IST)
        # 09:15 to 15:30 IST
        market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now_ist <= market_close

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._is_market_hours() and self._service._client.has_credentials:
                    log.debug("broker_intraday_poll")
                    # Use the same run_daily machinery but mark it as intraday
                    await self._service.run_daily(trigger="intraday_poll")
                elif not self._service._client.has_credentials:
                    log.debug("broker_intraday_poll_skipped_no_creds")
            except Exception as exc:
                log.warning("broker_intraday_poll_failed", error=str(exc))
            
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._settings.BROKER_INTRADAY_POLL_SECONDS
                )
            except TimeoutError:
                pass
