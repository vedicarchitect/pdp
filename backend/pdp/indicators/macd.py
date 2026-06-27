"""MACD indicator — fast/slow EMA lines + signal EMA + histogram, O(1) float64."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MACDState:
    macd: float      # fast_ema - slow_ema
    signal: float    # EMA of macd line
    histogram: float # macd - signal


class MACDTracker:
    """MACD tracker using incrementally updated EMAs.

    Seeds each EMA from an SMA of the first ``period`` closes, then applies
    exponential smoothing.  Returns None until the slow EMA is seeded and the
    signal EMA is also seeded (i.e. signal_period MACD values have been seen).
    """

    __slots__ = (
        "_fast",
        "_fast_alpha",
        "_fast_ema",
        "_history",
        "_macd_history",
        "_signal_alpha",
        "_signal_ema",
        "_signal_period",
        "_slow",
        "_slow_alpha",
        "_slow_ema",
    )

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError("fast period must be less than slow period")
        self._fast = fast
        self._slow = slow
        self._signal_period = signal
        self._fast_alpha = 2.0 / (fast + 1)
        self._slow_alpha = 2.0 / (slow + 1)
        self._signal_alpha = 2.0 / (signal + 1)
        self._fast_ema: float | None = None
        self._slow_ema: float | None = None
        self._signal_ema: float | None = None
        self._history: list[float] = []   # close accumulator until slow is seeded
        self._macd_history: list[float] = []  # MACD accumulator until signal is seeded

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> MACDState | None:
        if self._slow_ema is None:
            self._history.append(close)
            n = len(self._history)
            if n == self._fast:
                self._fast_ema = sum(self._history) / self._fast
            elif n > self._fast and self._fast_ema is not None:
                self._fast_ema = self._fast_alpha * close + (1.0 - self._fast_alpha) * self._fast_ema
            if n == self._slow:
                self._slow_ema = sum(self._history) / self._slow
                # fast_ema was already tracking; recalibrate from the same seed window
                # (We seed both from their respective SMA of the first N closes)
                self._fast_ema = sum(self._history[-self._fast:]) / self._fast
                self._history.clear()
            if self._slow_ema is None:
                return None
        else:
            self._fast_ema = self._fast_alpha * close + (1.0 - self._fast_alpha) * self._fast_ema  # type: ignore[operator]
            self._slow_ema = self._slow_alpha * close + (1.0 - self._slow_alpha) * self._slow_ema

        macd = self._fast_ema - self._slow_ema  # type: ignore[operator]

        if self._signal_ema is None:
            self._macd_history.append(macd)
            if len(self._macd_history) >= self._signal_period:
                self._signal_ema = sum(self._macd_history) / self._signal_period
                self._macd_history.clear()
            else:
                return None

        self._signal_ema = self._signal_alpha * macd + (1.0 - self._signal_alpha) * self._signal_ema
        return MACDState(macd=macd, signal=self._signal_ema, histogram=macd - self._signal_ema)
