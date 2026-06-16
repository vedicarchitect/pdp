"""VWMA indicator — volume-weighted moving average over a rolling window."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class VWMAState:
    vwma: float
    period: int


class VWMATracker:
    """Rolling-window VWMA using a bounded ring buffer (amortized O(1) per bar).

    Each slot stores ``(typical_price * volume, volume)``; the VWMA is their
    ratio summed over the window.
    """

    __slots__ = ("_period", "_buffer")

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self._period = period
        self._buffer: deque[tuple[float, float]] = deque(maxlen=period)

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> VWMAState | None:
        typical = (high + low + close) / 3.0
        self._buffer.append((typical * volume, volume))

        if len(self._buffer) < self._period:
            return None

        sum_pv = sum(pv for pv, _ in self._buffer)
        sum_v = sum(v for _, v in self._buffer)

        if sum_v <= 0:
            return None

        return VWMAState(vwma=sum_pv / sum_v, period=self._period)
