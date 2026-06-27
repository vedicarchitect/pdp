"""Fibonacci retracement and extension levels from the latest swing leg."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)
_EXTEND = (1.272, 1.618, 2.0)


@dataclass(slots=True)
class FibLevelsState:
    swing_high: float
    swing_low: float
    retracements: dict[float, float]  # ratio -> price level
    extensions: dict[float, float]    # ratio -> price level
    nearest_level: float              # price of the nearest Fib level to current price
    distance: float                   # signed distance: close - nearest_level
    last_reacted: float | None        # most recently touched Fib level price


class FibLevelsTracker:
    """Tracks Fibonacci retracement and extension levels from the latest swing leg.

    A ZigZag-lite detects swing direction changes with a ``threshold_pct`` reversal
    threshold. When a new confirmed leg is detected, levels are recomputed.
    ``nearest_level`` and ``distance`` are refreshed every bar.

    This is distinct from the existing ``PivotTracker`` Fibonacci pivot levels —
    those are computed from prior-session HLC; these are computed from swing structure.

    Parameters
    ----------
    threshold_pct:
        Minimum price reversal (as fraction of current price) to confirm a new swing.
    """

    __slots__ = (
        "_candidate_high",
        "_candidate_low",
        "_last_dir",
        "_last_reacted",
        "_state",
        "_swing_high",
        "_swing_low",
        "_threshold_pct",
    )

    def __init__(self, threshold_pct: float = 0.02) -> None:
        self._threshold_pct = threshold_pct
        self._swing_high: float | None = None
        self._swing_low: float | None = None
        self._last_dir: int = 0  # 1 = last swing was up, -1 = down
        self._candidate_high: float | None = None
        self._candidate_low: float | None = None
        self._last_reacted: float | None = None
        self._state: FibLevelsState | None = None

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> FibLevelsState | None:
        threshold = close * self._threshold_pct

        if self._candidate_high is None:
            self._candidate_high = high
            self._candidate_low = low
            return None

        self._candidate_high = max(self._candidate_high, high)
        self._candidate_low = min(self._candidate_low, low)  # type: ignore[arg-type]

        if self._last_dir != -1 and self._candidate_high is not None:
            if (self._candidate_high - low) >= threshold:
                # Reversal down: confirm the swing high
                if self._swing_low is None or self._candidate_high > (self._swing_low + threshold):
                    self._swing_high = self._candidate_high
                    if self._swing_low is None:
                        self._swing_low = low
                    self._last_dir = -1
                    self._candidate_low = low
                    self._candidate_high = high
        if self._last_dir != 1 and self._candidate_low is not None:
            if (high - self._candidate_low) >= threshold:
                # Reversal up: confirm the swing low
                if self._swing_high is None or self._candidate_low < (self._swing_high - threshold):
                    self._swing_low = self._candidate_low
                    if self._swing_high is None:
                        self._swing_high = high
                    self._last_dir = 1
                    self._candidate_high = high
                    self._candidate_low = low

        if self._swing_high is None or self._swing_low is None:
            return None

        sh = self._swing_high
        sl = self._swing_low
        leg = sh - sl

        retrace = {r: sh - r * leg for r in _RETRACE}
        extend_up = {e: sh + (e - 1.0) * leg for e in _EXTEND}

        all_levels = list(retrace.values()) + list(extend_up.values())

        # Nearest level and signed distance
        nearest = min(all_levels, key=lambda lvl: abs(lvl - close))
        distance = close - nearest

        # Detect most recently reacted level (bar touches within 0.1% of level)
        touch_tol = close * 0.001
        for lvl in all_levels:
            if abs(close - lvl) <= touch_tol or abs(low - lvl) <= touch_tol or abs(high - lvl) <= touch_tol:
                self._last_reacted = lvl
                break

        self._state = FibLevelsState(
            swing_high=sh,
            swing_low=sl,
            retracements=retrace,
            extensions=extend_up,
            nearest_level=nearest,
            distance=distance,
            last_reacted=self._last_reacted,
        )
        return self._state
