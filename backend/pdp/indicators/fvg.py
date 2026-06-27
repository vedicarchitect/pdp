"""Fair Value Gap (FVG) indicator — 3-bar gap detection with fill tracking."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FVGEntry:
    gap_type: str    # "bullish" or "bearish"
    gap_low: float
    gap_high: float
    filled: bool = False


@dataclass(slots=True)
class FVGState:
    unfilled_gaps: list[FVGEntry]
    total_gaps: int
    unfilled_count: int


class FVGTracker:
    """Detects fair-value gaps from the 3-bar pattern and tracks whether they are filled.

    Bullish FVG:  bar[n-2].high < bar[n].low   (gap up; bar[n-1] does not cover it)
    Bearish FVG:  bar[n-2].low  > bar[n].high  (gap down; bar[n-1] does not cover it)

    A bullish gap is filled when a later bar's low touches or penetrates the gap's bottom
    (bar[n-2].high).  A bearish gap is filled when a later bar's high touches or
    penetrates the gap's top (bar[n-2].low).
    """

    __slots__ = ("_max_gaps", "_bars", "_gaps")

    def __init__(self, max_gaps: int = 50) -> None:
        self._max_gaps = max_gaps
        self._bars: list[tuple[float, float]] = []  # (high, low) ring of last 3 bars
        self._gaps: list[FVGEntry] = []

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> FVGState | None:
        # Check existing gaps for fill
        for gap in self._gaps:
            if not gap.filled:
                if gap.gap_type == "bullish" and low <= gap.gap_low:
                    gap.filled = True
                elif gap.gap_type == "bearish" and high >= gap.gap_high:
                    gap.filled = True

        # Append current bar and keep only the last 3
        self._bars.append((high, low))
        if len(self._bars) > 3:
            self._bars.pop(0)

        # Detect new FVG from last 3 bars
        if len(self._bars) == 3:
            b0_h, b0_l = self._bars[0]  # two bars ago
            b2_h, b2_l = self._bars[2]  # current bar

            if b0_h < b2_l:  # bullish FVG: gap between b0.high and b2.low
                self._gaps.append(FVGEntry(gap_type="bullish", gap_low=b0_h, gap_high=b2_l))
            elif b0_l > b2_h:  # bearish FVG: gap between b2.high and b0.low
                self._gaps.append(FVGEntry(gap_type="bearish", gap_low=b2_h, gap_high=b0_l))

            # Prune to max_gaps (drop oldest)
            if len(self._gaps) > self._max_gaps:
                self._gaps = self._gaps[-self._max_gaps:]

        if not self._gaps:
            return None

        unfilled = [g for g in self._gaps if not g.filled]
        return FVGState(
            unfilled_gaps=unfilled,
            total_gaps=len(self._gaps),
            unfilled_count=len(unfilled),
        )
