"""Stale-feed watchdog.

Polls the TickRouter's last_tick_ts every second; if no ticks arrive within
FEED_STALE_SECONDS during market hours the watchdog emits a `feed_stale` log
event and triggers a reconnect on the DhanTickerAdapter.  It does NOT
auto-evict subscriptions — a silent market is legitimate.
"""

from __future__ import annotations

import asyncio
import time as _time
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.market.router import TickRouter

log = structlog.get_logger()

_MARKET_OPEN = (9, 15)
_MARKET_CLOSE = (15, 35)


def _in_market_hours() -> bool:
    import zoneinfo

    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = now.replace(hour=_MARKET_OPEN[0], minute=_MARKET_OPEN[1], second=0, microsecond=0)
    end = now.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    return start <= now <= end


class FeedWatchdog:
    """Monitors tick freshness and reconnects on sustained staleness."""

    def __init__(
        self,
        tick_router: TickRouter,
        adapter: DhanTickerAdapter,
        stale_seconds: int = 60,
    ) -> None:
        self._tick_router = tick_router
        self._adapter = adapter
        self._stale_seconds = stale_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="feed-watchdog")
        log.info("feed_watchdog_started", stale_seconds=self._stale_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            if not _in_market_hours():
                continue
            age = _time.monotonic() - self._tick_router.last_tick_ts
            if age > self._stale_seconds:
                log.warning(
                    "feed_stale",
                    stale_seconds=age,
                    threshold=self._stale_seconds,
                )
                await self._reconnect()

    async def _reconnect(self) -> None:
        """Signal the adapter to reconnect by stopping and restarting its feed task."""
        try:
            if self._adapter._feed is not None and self._adapter._connected:
                loop = asyncio.get_running_loop()
                feed = self._adapter._feed
                await loop.run_in_executor(None, feed.close_connection)
                log.info("feed_watchdog_reconnect_triggered")
        except Exception as exc:
            log.warning("feed_watchdog_reconnect_error", exc=str(exc))
