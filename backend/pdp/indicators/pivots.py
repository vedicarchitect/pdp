"""Pivot-level indicator — standard, Camarilla, and Fibonacci levels from prior-session HLC."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class PivotState:
    # Prior session OHLC used to compute these levels
    prior_h: float
    prior_l: float
    prior_c: float
    # Standard pivot
    pp: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float
    # Camarilla (pivot/R3/R4/S3/S4)
    cam_pp: float
    cam_r3: float
    cam_r4: float
    cam_s3: float
    cam_s4: float
    # Fibonacci
    fib_pp: float
    fib_r1: float
    fib_r2: float
    fib_r3: float
    fib_s1: float
    fib_s2: float
    fib_s3: float
    # Which session these levels apply to
    session_date: date


def _compute_pivots(h: float, l: float, c: float, session_date: date) -> PivotState:
    rng = h - l
    pp = (h + l + c) / 3.0

    # Standard
    r1 = 2.0 * pp - l
    r2 = pp + rng
    r3 = h + 2.0 * (pp - l)
    s1 = 2.0 * pp - h
    s2 = pp - rng
    s3 = l - 2.0 * (h - pp)

    # Camarilla
    cam_pp = pp
    cam_r3 = c + rng * 1.1 / 4.0
    cam_r4 = c + rng * 1.1 / 2.0
    cam_s3 = c - rng * 1.1 / 4.0
    cam_s4 = c - rng * 1.1 / 2.0

    # Fibonacci
    fib_pp = pp
    fib_r1 = pp + 0.382 * rng
    fib_r2 = pp + 0.618 * rng
    fib_r3 = pp + 1.000 * rng
    fib_s1 = pp - 0.382 * rng
    fib_s2 = pp - 0.618 * rng
    fib_s3 = pp - 1.000 * rng

    return PivotState(
        prior_h=h, prior_l=l, prior_c=c,
        pp=pp, r1=r1, r2=r2, r3=r3, s1=s1, s2=s2, s3=s3,
        cam_pp=cam_pp, cam_r3=cam_r3, cam_r4=cam_r4, cam_s3=cam_s3, cam_s4=cam_s4,
        fib_pp=fib_pp, fib_r1=fib_r1, fib_r2=fib_r2, fib_r3=fib_r3,
        fib_s1=fib_s1, fib_s2=fib_s2, fib_s3=fib_s3,
        session_date=session_date,
    )


class PivotTracker:
    """Computes standard/Camarilla/Fibonacci pivots once per session from prior-session HLC.

    Levels are held constant intrabar.  The prior-session HLC is accumulated during the
    trading day and used to compute levels at the start of the next session.
    """

    __slots__ = ("_session_h", "_session_l", "_session_c", "_current_date", "_state")

    def __init__(self) -> None:
        self._session_h: float | None = None
        self._session_l: float | None = None
        self._session_c: float | None = None
        self._current_date: date | None = None
        self._state: PivotState | None = None

    def seed_prior_hlc(self, h: float, l: float, c: float, prior_date: date | None = None) -> None:
        """Seed prior-session HLC directly (called by warmup before first live bar)."""
        session_date = prior_date or date.today()
        self._state = _compute_pivots(h, l, c, session_date)

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
    ) -> PivotState | None:
        session_date = bar_time.date() if bar_time is not None else None

        if session_date != self._current_date:
            # New session started: compute pivots from prior session's HLC
            if self._session_h is not None and session_date is not None:
                self._state = _compute_pivots(
                    self._session_h, self._session_l, self._session_c,  # type: ignore[arg-type]
                    session_date,
                )
            # Reset accumulators for the new session
            self._current_date = session_date
            self._session_h = high
            self._session_l = low
            self._session_c = close
        else:
            # Same session: track high/low and latest close
            if self._session_h is not None:
                self._session_h = max(self._session_h, high)
                self._session_l = min(self._session_l, low)  # type: ignore[type-var]
            else:
                self._session_h = high
                self._session_l = low
            self._session_c = close

        return self._state
