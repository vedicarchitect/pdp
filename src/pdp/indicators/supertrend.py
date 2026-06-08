"""SuperTrend indicator — pure, stateful, O(1) per bar.

SuperTrend is an ATR-banded trend follower. With ``period=3, multiplier=1`` it reacts
quickly, which suits intraday signal flipping. Direction is ``+1`` (uptrend / "green") when
price closes above the trailing line and ``-1`` (downtrend / "red") when it closes below.

The tracker uses Wilder's ATR (SMA seed over the first ``period`` true ranges, then Wilder
smoothing) and the standard final upper/lower band carry-over so values match common
charting libraries (TradingView / pandas-ta).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

UP = 1
DOWN = -1

_TWO = Decimal("2")


@dataclass(slots=True)
class SuperTrendState:
    direction: int  # UP (+1) or DOWN (-1)
    value: Decimal  # the SuperTrend line value at this bar
    flipped: bool  # True if direction changed on this bar
    bar_time: datetime | None = None


def _d(v: Decimal | float | int | str) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


class SuperTrendTracker:
    """Stateful SuperTrend for a single series. Feed bars in chronological order."""

    __slots__ = (
        "_atr",
        "_direction",
        "_final_lower",
        "_final_upper",
        "_multiplier",
        "_prev_close",
        "_supertrend",
        "_tr_seed",
        "period",
    )

    def __init__(self, period: int = 3, multiplier: Decimal | float | int = 1) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._multiplier = _d(multiplier)
        self._prev_close: Decimal | None = None
        self._tr_seed: list[Decimal] = []
        self._atr: Decimal | None = None
        self._final_upper: Decimal | None = None
        self._final_lower: Decimal | None = None
        self._supertrend: Decimal | None = None
        self._direction: int | None = None

    @property
    def direction(self) -> int | None:
        return self._direction

    def update(
        self,
        high: Decimal | float | int | str,
        low: Decimal | float | int | str,
        close: Decimal | float | int | str,
        bar_time: datetime | None = None,
    ) -> SuperTrendState | None:
        """Push one bar. Returns the new state, or ``None`` until ATR is seeded."""
        high = _d(high)
        low = _d(low)
        close = _d(close)

        # True range (first bar has no previous close)
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )

        # Seed ATR with an SMA of the first ``period`` true ranges.
        if self._atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) < self.period:
                self._prev_close = close
                return None
            self._atr = sum(self._tr_seed, Decimal("0")) / Decimal(self.period)
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / Decimal(self.period)

        prev_close = self._prev_close  # previous bar's close (not None at this point)
        hl2 = (high + low) / _TWO
        basic_upper = hl2 + self._multiplier * self._atr
        basic_lower = hl2 - self._multiplier * self._atr

        # Final band carry-over (tighten unless price breaks the prior band).
        if self._final_upper is None or prev_close is None:
            final_upper = basic_upper
            final_lower = basic_lower
        else:
            final_upper = (
                basic_upper
                if (basic_upper < self._final_upper or prev_close > self._final_upper)
                else self._final_upper
            )
            final_lower = (
                basic_lower
                if (basic_lower > self._final_lower or prev_close < self._final_lower)
                else self._final_lower
            )

        # Determine the SuperTrend line and direction.
        if self._supertrend is None:
            if close <= final_upper:
                supertrend = final_upper
                direction = DOWN
            else:
                supertrend = final_lower
                direction = UP
        elif self._supertrend == self._final_upper:
            # Previously in the downtrend (upper) band.
            if close > final_upper:
                supertrend, direction = final_lower, UP
            else:
                supertrend, direction = final_upper, DOWN
        else:
            # Previously in the uptrend (lower) band.
            if close < final_lower:
                supertrend, direction = final_upper, DOWN
            else:
                supertrend, direction = final_lower, UP

        flipped = self._direction is not None and direction != self._direction

        self._final_upper = final_upper
        self._final_lower = final_lower
        self._supertrend = supertrend
        self._direction = direction
        self._prev_close = close

        return SuperTrendState(
            direction=direction, value=supertrend, flipped=flipped, bar_time=bar_time
        )


def supertrend(
    highs: list,
    lows: list,
    closes: list,
    period: int = 3,
    multiplier: Decimal | float | int = 1,
) -> list[SuperTrendState | None]:
    """Batch helper — returns one state per input bar (``None`` while seeding)."""
    tracker = SuperTrendTracker(period, multiplier)
    out: list[SuperTrendState | None] = []
    for h, low, c in zip(highs, lows, closes, strict=True):
        out.append(tracker.update(h, low, c))
    return out
