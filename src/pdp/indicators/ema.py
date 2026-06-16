"""EMA indicator — multi-period exponential moving average, O(1) incremental float64."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class EMAState:
    values: dict[int, float]  # period -> EMA value; only seeded periods present


class EMATracker:
    """Stateful multi-period EMA tracker.

    Seeds each period from an SMA of the first ``period`` closes, then applies
    ``ema = a*close + (1-a)*ema`` with ``a = 2/(period+1)`` incrementally.
    """

    __slots__ = ("_periods", "_alpha", "_values", "_history", "_seeded")

    def __init__(self, periods: list[int] | None = None) -> None:
        self._periods: list[int] = sorted(periods or [9, 20, 50, 100, 200])
        self._alpha: dict[int, float] = {p: 2.0 / (p + 1) for p in self._periods}
        self._values: dict[int, float | None] = {p: None for p in self._periods}
        self._history: list[float] = []
        self._seeded = False

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> EMAState | None:
        if self._seeded:
            for p in self._periods:
                a = self._alpha[p]
                self._values[p] = a * close + (1.0 - a) * self._values[p]  # type: ignore[operator]
        else:
            self._history.append(close)
            n = len(self._history)
            all_seeded = True
            for p in self._periods:
                if self._values[p] is None:
                    if n == p:
                        self._values[p] = sum(self._history) / p
                    else:
                        all_seeded = False
                else:
                    a = self._alpha[p]
                    self._values[p] = a * close + (1.0 - a) * self._values[p]  # type: ignore[operator]
            if all_seeded:
                self._seeded = True
                self._history.clear()

        if self._values[self._periods[0]] is None:
            return None
        return EMAState(values={p: v for p, v in self._values.items() if v is not None})  # type: ignore[misc]

    @property
    def periods(self) -> list[int]:
        return list(self._periods)
