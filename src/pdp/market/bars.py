from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.market.models import Tick

log = structlog.get_logger()

# Supported timeframes: label → window in minutes (60 = 1H).
# "1D" uses IST calendar-day boundaries, not minute intervals.
_TIMEFRAMES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "1D": -1,  # sentinel: handled by _bar_boundary_1d
}

# IST = UTC+5:30
_IST_OFFSET_MINUTES = 5 * 60 + 30

# Maximum seconds ltt can lead ts_recv before we fall back to ts_recv
_MAX_LTT_LEAD_S = 2.0


@dataclass(slots=True)
class BarClosed:
    security_id: str
    timeframe: str
    bar_time: datetime  # UTC truncated to timeframe boundary
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int


def _bar_boundary(dt: datetime, tf_minutes: int) -> datetime:
    """Truncate dt to the nearest tf_minutes boundary (UTC)."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = dt - epoch
    total_minutes = int(delta.total_seconds() // 60)
    truncated_minutes = (total_minutes // tf_minutes) * tf_minutes
    return epoch + timedelta(minutes=truncated_minutes)


def _bar_boundary_1d(dt: datetime) -> datetime:
    """Return the IST calendar-day start (in UTC) for a given UTC datetime.

    IST midnight = UTC 18:30 the previous calendar day. All NSE session bars
    from ~03:45 UTC to ~10:00 UTC share the same IST date and are placed in the
    same 1D bucket.
    """
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    total_minutes = int(dt.timestamp() // 60) + _IST_OFFSET_MINUTES
    ist_day_start_min = (total_minutes // (24 * 60)) * (24 * 60)
    utc_day_start_min = ist_day_start_min - _IST_OFFSET_MINUTES
    return epoch + timedelta(minutes=utc_day_start_min)


class BarBuilder:
    """Accumulates ticks for one (security_id, timeframe) into OHLCV bars."""

    __slots__ = (
        "_bar_time",
        "_close",
        "_high",
        "_is_daily",
        "_low",
        "_oi",
        "_open",
        "_tf_minutes",
        "_volume",
        "security_id",
        "timeframe",
    )

    def __init__(self, security_id: str, timeframe: str) -> None:
        self.security_id = security_id
        self.timeframe = timeframe
        self._tf_minutes = _TIMEFRAMES[timeframe]
        self._is_daily = timeframe == "1D"
        self._bar_time: datetime | None = None
        self._open = self._high = self._low = self._close = Decimal("0")
        self._volume = 0
        self._oi = 0

    def push(self, tick: Tick) -> BarClosed | None:
        """Push one tick into the builder.  Returns a BarClosed event if a bar just closed."""
        # Stale-ltt protection: if ltt leads ts_recv by > 2s, use ts_recv
        now_wall = time.monotonic()
        ltt_epoch = tick.ltt.timestamp()

        # Convert ts_recv (monotonic) to approx wall clock:
        # wall_now - (monotonic_now - ts_recv)
        approx_recv_wall = time.time() - (now_wall - tick.ts_recv)
        approx_recv_dt = datetime.fromtimestamp(approx_recv_wall, tz=UTC)

        if ltt_epoch > approx_recv_wall + _MAX_LTT_LEAD_S:
            effective_dt = approx_recv_dt
        else:
            effective_dt = tick.ltt if tick.ltt.tzinfo else tick.ltt.replace(tzinfo=UTC)

        boundary = (
            _bar_boundary_1d(effective_dt)
            if self._is_daily
            else _bar_boundary(effective_dt, self._tf_minutes)
        )

        closed_bar: BarClosed | None = None

        if self._bar_time is None:
            # First tick — open new bar
            self._reset(boundary, tick)
        elif boundary != self._bar_time:
            # Boundary crossed — emit closed bar, open new one
            closed_bar = self._snapshot()
            self._reset(boundary, tick)
        else:
            # Same bar — accumulate
            ltp = tick.ltp
            if ltp > self._high:
                self._high = ltp
            if ltp < self._low:
                self._low = ltp
            self._close = ltp
            self._volume += tick.volume
            self._oi = tick.oi

        return closed_bar

    def _reset(self, bar_time: datetime, tick: Tick) -> None:
        self._bar_time = bar_time
        self._open = self._high = self._low = self._close = tick.ltp
        self._volume = tick.volume
        self._oi = tick.oi

    def _snapshot(self) -> BarClosed:
        assert self._bar_time is not None
        return BarClosed(
            security_id=self.security_id,
            timeframe=self.timeframe,
            bar_time=self._bar_time,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            oi=self._oi,
        )


class BarAggregator:
    """
    Holds one BarBuilder per (security_id, timeframe).
    Builders are created lazily on first tick.
    """

    def __init__(self, timeframes: list[str] | None = None) -> None:
        self._timeframes = timeframes or list(_TIMEFRAMES.keys())
        self._builders: dict[tuple[str, str], BarBuilder] = {}

    def push(self, tick: Tick) -> list[BarClosed]:
        """Push a tick to all active timeframe builders; return any closed bars."""
        closed: list[BarClosed] = []
        for tf in self._timeframes:
            key = (tick.security_id, tf)
            builder = self._builders.get(key)
            if builder is None:
                builder = BarBuilder(tick.security_id, tf)
                self._builders[key] = builder
            result = builder.push(tick)
            if result is not None:
                closed.append(result)
        return closed
