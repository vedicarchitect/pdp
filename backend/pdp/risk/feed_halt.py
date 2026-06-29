"""Feed-stale safe-halt.

When a feed_stale condition persists longer than FEED_STALE_HALT_SECONDS the
live-entry gate is engaged: OrderRouter checks `FeedStaleHalt.live_blocked`
before routing to DhanBroker.  Paper orders are unaffected.  Clearing the stall
does not auto-resume — the operator must explicitly call clear().
"""

from __future__ import annotations

import asyncio
import time as _time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()


class FeedStaleHalt:
    """Single-writer, many-reader halt gate driven by stale-feed events."""

    def __init__(self, halt_after_seconds: int = 180) -> None:
        self._halt_after = halt_after_seconds
        self._stale_since: float | None = None
        self._halted = False
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def live_blocked(self) -> bool:
        return self._halted

    def on_feed_stale(self) -> None:
        """Called by the watchdog each time it detects staleness."""
        if self._stale_since is None:
            self._stale_since = _time.monotonic()
            log.info("feed_stale_halt_timer_started", halt_after=self._halt_after)
        elapsed = _time.monotonic() - self._stale_since
        if not self._halted and elapsed >= self._halt_after:
            self._halted = True
            log.warning(
                "feed_stale_halt_engaged",
                elapsed_seconds=elapsed,
                halt_after=self._halt_after,
            )

    def on_feed_recovered(self) -> None:
        """Called when ticks resume — clears the timer but NOT the halt (operator resumes)."""
        if self._stale_since is not None:
            log.info("feed_stale_timer_cleared", was_halted=self._halted)
        self._stale_since = None

    def clear(self) -> None:
        """Operator-initiated resume after manual inspection."""
        self._halted = False
        self._stale_since = None
        log.info("feed_stale_halt_cleared")

    async def start(self) -> None:
        pass  # stateless; no background task needed

    async def stop(self) -> None:
        pass
