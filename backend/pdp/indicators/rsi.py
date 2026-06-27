"""RSI indicator — Wilder's running average + EMA signal line (MA), O(1) float64."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RSIState:
    rsi: float
    avg_gain: float
    avg_loss: float
    ma: float | None = None  # EMA signal line of RSI; None until ma_period RSI values are seen


class RSITracker:
    """Stateful RSI tracker using Wilder's smoothing, with an optional EMA signal line.

    Seeds avg_gain / avg_loss from the SMA of the first ``period`` changes,
    then applies Wilder's running average incrementally.  Once ``ma_period`` RSI
    values are available the signal line is seeded from their SMA and then updated
    incrementally as ``ma = alpha * rsi + (1 - alpha) * ma``.
    """

    __slots__ = (
        "_avg_gain", "_avg_loss", "_ma_alpha", "_ma_history", "_ma_period",
        "_ma_value", "_period", "_prev_close", "_seed_changes",
    )

    def __init__(self, period: int = 14, ma_period: int = 9) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        if ma_period < 1:
            raise ValueError("ma_period must be >= 1")
        self._period = period
        self._prev_close: float | None = None
        self._seed_changes: list[tuple[float, float]] = []  # (gain, loss) pairs
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._ma_period = ma_period
        self._ma_alpha = 2.0 / (ma_period + 1)
        self._ma_value: float | None = None
        self._ma_history: list[float] = []  # RSI accumulator until MA is seeded

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> RSIState | None:
        if self._prev_close is None:
            self._prev_close = close
            return None

        change = close - self._prev_close
        self._prev_close = close
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0

        if self._avg_gain is None:
            self._seed_changes.append((gain, loss))
            if len(self._seed_changes) < self._period:
                return None
            self._avg_gain = sum(g for g, _ in self._seed_changes) / self._period
            self._avg_loss = sum(lv for _, lv in self._seed_changes) / self._period
            self._seed_changes.clear()
        else:
            self._avg_gain = (self._avg_gain * (self._period - 1) + gain) / self._period
            self._avg_loss = (self._avg_loss * (self._period - 1) + loss) / self._period  # type: ignore[operator]

        if self._avg_loss == 0.0:
            rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss  # type: ignore[operator]
            rsi = 100.0 - 100.0 / (1.0 + rs)

        # Update EMA signal line of RSI
        if self._ma_value is None:
            self._ma_history.append(rsi)
            if len(self._ma_history) >= self._ma_period:
                self._ma_value = sum(self._ma_history) / self._ma_period
                self._ma_history.clear()
        else:
            self._ma_value = self._ma_alpha * rsi + (1.0 - self._ma_alpha) * self._ma_value

        return RSIState(rsi=rsi, avg_gain=self._avg_gain, avg_loss=self._avg_loss, ma=self._ma_value)  # type: ignore[arg-type]
