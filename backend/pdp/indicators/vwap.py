"""VWAP indicator — session-anchored volume-weighted average price."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class VWAPState:
    vwap: float
    session_date: date


class VWAPTracker:
    """Running VWAP reset at the start of each trading session.

    Uses the UTC date of ``bar_time`` as the session key, which is correct for NIFTY
    (all bars 03:45-10:00 UTC fall on the same UTC calendar date as IST session date).
    """

    __slots__ = ("_sum_pv", "_sum_v", "_session_date", "_state")

    def __init__(self) -> None:
        self._sum_pv: float = 0.0
        self._sum_v: float = 0.0
        self._session_date: date | None = None
        self._state: VWAPState | None = None

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> VWAPState | None:
        session_date = bar_time.date() if bar_time is not None else None

        if session_date != self._session_date:
            self._sum_pv = 0.0
            self._sum_v = 0.0
            self._session_date = session_date

        if volume > 0:
            typical = (high + low + close) / 3.0
            self._sum_pv += typical * volume
            self._sum_v += volume

        if self._sum_v <= 0:
            return None

        vwap = self._sum_pv / self._sum_v
        self._state = VWAPState(vwap=vwap, session_date=session_date)  # type: ignore[arg-type]
        return self._state
