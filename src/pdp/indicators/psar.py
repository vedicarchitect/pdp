"""Parabolic SAR indicator — EP/AF flip algorithm, O(1) per bar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ParabolicSARState:
    sar: float
    direction: int   # 1 = uptrend, -1 = downtrend
    ep: float        # extreme point
    af: float        # current acceleration factor


class ParabolicSARTracker:
    """Stateful Parabolic SAR tracker.

    Initialises on the second bar.  In an uptrend the SAR is below price (ep=highest
    high); in a downtrend the SAR is above price (ep=lowest low).  When price crosses the
    SAR the trend flips, AF resets to ``step``, and SAR jumps to the prior ep.
    """

    __slots__ = (
        "_af",
        "_bars",
        "_direction",
        "_ep",
        "_max_step",
        "_pp_high",
        "_pp_low",
        "_prev_high",
        "_prev_low",
        "_sar",
        "_step",
    )

    def __init__(self, step: float = 0.02, max_step: float = 0.2) -> None:
        self._step = step
        self._max_step = max_step
        self._af: float = step
        self._ep: float | None = None
        self._sar: float | None = None
        self._direction: int | None = None
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._pp_high: float | None = None  # bar n-2 high
        self._pp_low: float | None = None
        self._bars = 0

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> ParabolicSARState | None:
        self._bars += 1

        if self._bars == 1:
            self._prev_high = high
            self._prev_low = low
            return None

        if self._bars == 2:
            # Initialise direction: uptrend if current close > prior bar's high
            if close >= self._prev_high:  # type: ignore[operator]
                self._direction = 1
                self._sar = self._prev_low
                self._ep = high
            else:
                self._direction = -1
                self._sar = self._prev_high
                self._ep = low
            self._af = self._step
            self._pp_high = self._prev_high
            self._pp_low = self._prev_low
            self._prev_high = high
            self._prev_low = low
            return ParabolicSARState(sar=self._sar, direction=self._direction, ep=self._ep, af=self._af)  # type: ignore[arg-type]

        prev_sar = self._sar
        prev_ep = self._ep
        prev_af = self._af
        prev_dir = self._direction

        new_sar = prev_sar + prev_af * (prev_ep - prev_sar)  # type: ignore[operator]

        if prev_dir == 1:  # uptrend
            new_sar = min(new_sar, self._prev_low, self._pp_low)  # type: ignore[arg-type]
            if low < new_sar:
                # Reversal → downtrend
                self._direction = -1
                new_sar = prev_ep
                self._ep = low
                self._af = self._step
            else:
                if high > self._ep:  # type: ignore[operator]
                    self._ep = high
                    self._af = min(self._af + self._step, self._max_step)  # type: ignore[operator]
        else:  # downtrend
            new_sar = max(new_sar, self._prev_high, self._pp_high)  # type: ignore[arg-type]
            if high > new_sar:
                # Reversal → uptrend
                self._direction = 1
                new_sar = prev_ep
                self._ep = high
                self._af = self._step
            else:
                if low < self._ep:  # type: ignore[operator]
                    self._ep = low
                    self._af = min(self._af + self._step, self._max_step)  # type: ignore[operator]

        self._sar = new_sar
        self._pp_high = self._prev_high
        self._pp_low = self._prev_low
        self._prev_high = high
        self._prev_low = low

        return ParabolicSARState(sar=self._sar, direction=self._direction, ep=self._ep, af=self._af)  # type: ignore[arg-type]
