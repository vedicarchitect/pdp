"""Elliott Wave structure — ZigZag swing pivots + heuristic impulse/corrective labeler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ElliottWaveState:
    wave_label: str | None   # "1"-"5" (impulse) or "A"/"B"/"C" (corrective), None if unclear
    wave_position: int | None  # 0-based position in the current sequence (0-4 for impulse)
    confidence: float          # 0.0 - 1.0 heuristic confidence
    swing_high: float | None   # last confirmed swing high
    swing_low: float | None    # last confirmed swing low
    trend: int                 # 1 = uptrend, -1 = downtrend, 0 = unknown


class ElliottWaveTracker:
    """Heuristic Elliott Wave labeler built on a ZigZag swing-pivot detector.

    The ZigZag records alternating swings: each new swing must reverse by at
    least ``threshold_pct`` percent of the preceding swing's range (or
    ``threshold_atr`` x ATR if provided via the ``atr`` method, though the
    simpler pct mode is the default).

    Wave labels are **heuristic and probabilistic** — they are ML features,
    not hard trading rules. Returns None until at least 4 pivots are confirmed.

    Parameters
    ----------
    threshold_pct:
        Minimum reversal as a fraction of current price (default 0.02 = 2 %).
    min_pivots:
        Pivots required before emitting a label (default 4).
    """

    __slots__ = ("_atr", "_min_pivots", "_pivots", "_prev_close", "_threshold_pct")

    def __init__(self, threshold_pct: float = 0.02, min_pivots: int = 4) -> None:
        self._threshold_pct = threshold_pct
        self._min_pivots = min_pivots
        # Each pivot is (price, direction) where direction = 1 for high, -1 for low
        self._pivots: list[tuple[float, int]] = []
        self._atr: float | None = None  # smoothed ATR (Wilder, period=14)
        self._prev_close: float | None = None

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> ElliottWaveState | None:
        # Update ATR (Wilder's smoothing, period=14)
        if self._prev_close is not None:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
            self._atr = tr if self._atr is None else (self._atr * 13.0 + tr) / 14.0
        self._prev_close = close

        # ZigZag pivot detection
        threshold = close * self._threshold_pct

        if not self._pivots:
            # Seed with both a low and a high from the first bar
            self._pivots.append((low, -1))
            self._pivots.append((high, 1))
            return None

        last_price, last_dir = self._pivots[-1]

        if last_dir == 1:  # last pivot was a high — looking for reversal down
            if high > last_price:
                # Extend the current high pivot
                self._pivots[-1] = (high, 1)
            elif last_price - low >= threshold:
                # New swing low pivot
                self._pivots.append((low, -1))
        else:  # last pivot was a low — looking for reversal up
            if low < last_price:
                # Extend the current low pivot
                self._pivots[-1] = (low, -1)
            elif high - last_price >= threshold:
                # New swing high pivot
                self._pivots.append((high, 1))

        if len(self._pivots) < self._min_pivots:
            return None

        return self._label(close)

    def _label(self, close: float) -> ElliottWaveState:
        """Apply heuristic wave labeling to the current pivot sequence."""
        pivots = self._pivots[-8:]  # use last 8 pivots for labeling

        # Determine dominant trend from first-to-last pivot
        first_price = pivots[0][0]
        last_price = pivots[-1][0]
        trend = 1 if last_price > first_price else -1

        # Collect swing legs (alternating highs/lows)
        legs: list[float] = []
        for i in range(1, len(pivots)):
            legs.append(abs(pivots[i][0] - pivots[i - 1][0]))

        n_legs = len(legs)
        wave_label: str | None = None
        wave_position: int | None = None
        confidence = 0.0

        if trend == 1 and n_legs >= 5:
            # Impulse up: legs should follow 1>2<3>4<5 size pattern (3 largest)
            # Check basic impulse rule: wave 3 is not shortest
            w1, _w2, w3, _w4 = legs[-5], legs[-4], legs[-3], legs[-2]
            w5 = legs[-1]
            if w3 >= min(w1, w5):
                wave_label = "5"
                wave_position = 4
                confidence = min(1.0, (w3 / max(w1, w5)) * 0.6)
        elif trend == -1 and n_legs >= 5:
            # Corrective A-B-C: A down, B up, C down
            a, _b, c = legs[-3], legs[-2], legs[-1]
            last_dir = pivots[-1][1]
            if last_dir == -1:  # ended on a low = completed C leg
                wave_label = "C"
                wave_position = 2
                confidence = min(1.0, (c / a) * 0.5 + 0.2)
            else:
                wave_label = "B"
                wave_position = 1
                confidence = 0.3

        if wave_label is None and n_legs >= 2:
            # Fallback: label by position in last 2 legs
            last_dir = pivots[-1][1]
            if trend == 1:
                wave_label = "3" if last_dir == 1 else "2"
                wave_position = 2 if last_dir == 1 else 1
            else:
                wave_label = "A" if last_dir == -1 else "B"
                wave_position = 0 if last_dir == -1 else 1
            confidence = 0.2

        return ElliottWaveState(
            wave_label=wave_label,
            wave_position=wave_position,
            confidence=confidence,
            swing_high=max((p for p, d in self._pivots[-4:] if d == 1), default=None),
            swing_low=min((p for p, d in self._pivots[-4:] if d == -1), default=None),
            trend=trend,
        )
