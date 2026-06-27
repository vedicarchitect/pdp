"""Elder Impulse System — 13-EMA slope x MACD-histogram slope -> green/red/blue regime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pdp.indicators.macd import MACDState, MACDTracker


@dataclass(slots=True)
class ElderImpulseState:
    regime: str        # "green" (both rising), "red" (both falling), "blue" (mixed)
    ema13_rising: bool
    macd_hist_rising: bool


class ElderImpulseTracker:
    """Elder Impulse tracker combining a 13-period EMA trend and MACD momentum.

    Regime:
    - **green**: 13-EMA rising AND MACD histogram rising → strong trend
    - **red**: 13-EMA falling AND MACD histogram falling → strong counter-trend
    - **blue**: directions disagree → uncertain / transitional

    Depends on MACDTracker internally (default 12/26/9).  Returns None until
    both the EMA and MACD are seeded.
    """

    __slots__ = (
        "_ema",
        "_ema_alpha",
        "_ema_period",
        "_ema_prev",
        "_macd",
        "_prev_hist",
    )

    def __init__(
        self,
        ema_period: int = 13,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
    ) -> None:
        self._ema_period = ema_period
        self._ema_alpha = 2.0 / (ema_period + 1)
        self._ema: float | None = None
        self._ema_prev: float | None = None
        self._macd = MACDTracker(fast=macd_fast, slow=macd_slow, signal=macd_signal)
        self._prev_hist: float | None = None

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> ElderImpulseState | None:
        # 13-EMA update
        if self._ema is None:
            # Seed from first close (simplest seed — full SMA seed needs period bars)
            self._ema = close
        else:
            self._ema_prev = self._ema
            self._ema = self._ema_alpha * close + (1.0 - self._ema_alpha) * self._ema

        # MACD update
        macd_state: MACDState | None = self._macd.update(high, low, close, volume, bar_time)

        if macd_state is None or self._ema_prev is None:
            return None

        ema13_rising = self._ema > self._ema_prev
        macd_hist_rising = (
            self._prev_hist is None or macd_state.histogram > self._prev_hist
        )
        self._prev_hist = macd_state.histogram

        if ema13_rising and macd_hist_rising:
            regime = "green"
        elif not ema13_rising and not macd_hist_rising:
            regime = "red"
        else:
            regime = "blue"

        return ElderImpulseState(
            regime=regime,
            ema13_rising=ema13_rising,
            macd_hist_rising=macd_hist_rising,
        )
