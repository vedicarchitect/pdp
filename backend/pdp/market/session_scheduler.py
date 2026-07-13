"""Session-end flush scheduler for BarAggregator.

A lightweight asyncio loop that closes the final open bucket of every (security_id,
timeframe) at session close (15:30 IST), once per trading day. Idempotent: at most one
flush per IST calendar date. Trading-day gated via the NSE holiday calendar (not a bare
weekday check), so a weekday holiday doesn't get treated as tradeable.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.market.bars import BarAggregator

log = structlog.get_logger()

_IST = timezone(timedelta(hours=5, minutes=30))
_DEFAULT_FLUSH_TIME = (15, 30)


class BarSessionScheduler:
    def __init__(
        self,
        bar_aggregator: BarAggregator,
        holiday_set: set[date],
        flush_time: tuple[int, int] = _DEFAULT_FLUSH_TIME,
    ) -> None:
        self._aggregator = bar_aggregator
        self._holiday_set = holiday_set
        self._target = flush_time
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._last_flushed: date | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="bar-session-flush")
        log.info(
            "bar_session_scheduler_started",
            flush_time=f"{self._target[0]:02d}:{self._target[1]:02d}",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holiday_set

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now(_IST)
                today = now.date()
                past_target = (now.hour, now.minute) >= self._target
                if past_target and self._last_flushed != today and self._is_trading_day(today):
                    closed = self._aggregator.flush_session()
                    self._last_flushed = today
                    log.info("bar_session_flush", session_date=str(today), bars_closed=len(closed))
            except Exception as exc:
                log.warning("bar_session_scheduler_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                pass
