"""Live indicator engine.

Keeps one ``SuperTrendTracker`` per ``(security_id, timeframe)`` and updates it on each
closed bar. Driven by ``TickRouter`` before strategy dispatch so strategies read the value
computed for the just-closed bar (rule #4: indicators computed once, consumed by all).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from pdp.indicators.supertrend import SuperTrendState, SuperTrendTracker

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed

log = structlog.get_logger()


class IndicatorEngine:
    def __init__(
        self,
        st_period: int = 3,
        st_multiplier: float = 1,
        timeframes: list[str] | None = None,
    ) -> None:
        self._period = st_period
        self._multiplier = st_multiplier
        # When set, only these timeframes are tracked; None = all timeframes.
        self._timeframes: set[str] | None = set(timeframes) if timeframes else None
        self._trackers: dict[tuple[str, str], SuperTrendTracker] = {}
        self._latest: dict[tuple[str, str], SuperTrendState] = {}

    def on_bar(self, bar: BarClosed) -> SuperTrendState | None:
        """Update the SuperTrend for this bar's (security, timeframe). Returns the state."""
        if self._timeframes is not None and bar.timeframe not in self._timeframes:
            return None
        key = (bar.security_id, bar.timeframe)
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = SuperTrendTracker(self._period, self._multiplier)
            self._trackers[key] = tracker
        state = tracker.update(bar.high, bar.low, bar.close, bar.bar_time)
        if state is not None:
            self._latest[key] = state
        return state

    def get(self, security_id: str, timeframe: str) -> SuperTrendState | None:
        """Latest computed SuperTrend for the pair, or None if not yet seeded."""
        return self._latest.get((security_id, timeframe))
