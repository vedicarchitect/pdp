"""Previous-period high/low levels — PDH/PDL, PWH/PWL, PMH/PML.

Tracks the current day / ISO-week / calendar-month high-low accumulators and
freezes each completed period's high-low at the corresponding boundary. The
frozen values are the *previous* period's extremes:

  - ``pdh`` / ``pdl`` — previous trading day high / low
  - ``pwh`` / ``pwl`` — previous ISO-week high / low
  - ``pmh`` / ``pml`` — previous calendar-month high / low

Grouping uses ``bar_time.date()`` (UTC) to match ``PivotTracker``; the NIFTY
session never crosses UTC midnight, so the UTC date equals the IST session date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class PeriodLevelsState:
    pdh: float | None = None
    pdl: float | None = None
    pwh: float | None = None
    pwl: float | None = None
    pmh: float | None = None
    pml: float | None = None


class PeriodLevelsTracker:
    """Accumulates day/week/month high-low and freezes prior-period extremes at boundaries."""

    __slots__ = (
        "_day_h",
        "_day_key",
        "_day_l",
        "_month_h",
        "_month_key",
        "_month_l",
        "_state",
        "_week_h",
        "_week_key",
        "_week_l",
    )

    def __init__(self) -> None:
        self._day_key: date | None = None
        self._day_h: float | None = None
        self._day_l: float | None = None
        self._week_key: tuple[int, int] | None = None
        self._week_h: float | None = None
        self._week_l: float | None = None
        self._month_key: tuple[int, int] | None = None
        self._month_h: float | None = None
        self._month_l: float | None = None
        self._state = PeriodLevelsState()

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> PeriodLevelsState | None:
        if bar_time is None:
            return self._state

        d = bar_time.date()
        iso = d.isocalendar()
        wk = (iso[0], iso[1])
        mo = (d.year, d.month)

        # Day
        if self._day_key is None:
            self._day_key, self._day_h, self._day_l = d, high, low
        elif d != self._day_key:
            self._state.pdh, self._state.pdl = self._day_h, self._day_l
            self._day_key, self._day_h, self._day_l = d, high, low
        else:
            self._day_h = max(self._day_h, high)  # type: ignore[type-var]
            self._day_l = min(self._day_l, low)  # type: ignore[type-var]

        # ISO week
        if self._week_key is None:
            self._week_key, self._week_h, self._week_l = wk, high, low
        elif wk != self._week_key:
            self._state.pwh, self._state.pwl = self._week_h, self._week_l
            self._week_key, self._week_h, self._week_l = wk, high, low
        else:
            self._week_h = max(self._week_h, high)  # type: ignore[type-var]
            self._week_l = min(self._week_l, low)  # type: ignore[type-var]

        # Calendar month
        if self._month_key is None:
            self._month_key, self._month_h, self._month_l = mo, high, low
        elif mo != self._month_key:
            self._state.pmh, self._state.pml = self._month_h, self._month_l
            self._month_key, self._month_h, self._month_l = mo, high, low
        else:
            self._month_h = max(self._month_h, high)  # type: ignore[type-var]
            self._month_l = min(self._month_l, low)  # type: ignore[type-var]

        return self._state
