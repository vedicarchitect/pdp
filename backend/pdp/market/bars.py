from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pdp.market.models import Tick

log = structlog.get_logger()

# Supported timeframes: label → window in minutes (60 = 1H).
# "1D" uses IST calendar-day boundaries, not minute intervals.
# "1w" uses ISO-week boundaries (Monday 00:00 IST = Sunday 18:30 UTC).
_TIMEFRAMES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "1D": -1,  # sentinel: handled by _bar_boundary_1d
    "1w": -2,  # sentinel: handled by _bar_boundary_1w
}

# IST = UTC+5:30
_IST_OFFSET_MINUTES = 5 * 60 + 30

# Trading session window, IST minutes-since-midnight: [09:15, 15:30)
_SESSION_OPEN_MIN_OF_DAY = 9 * 60 + 15
_SESSION_CLOSE_MIN_OF_DAY = 15 * 60 + 30

# Maximum seconds ltt can lead ts_recv before we fall back to ts_recv
_MAX_LTT_LEAD_S = 2.0

# Bar period per timeframe label, for completeness checks on broker-fetched bars
# (dhan-same-day-data). 1D/1w are deliberately the full calendar day/week rather
# than the session close (15:30 IST) — Dhan's daily-candle semantics for an
# in-progress trading day are unverified, so this errs toward discarding a
# same-day daily/weekly bar rather than risking a partial one in market_bars.
_BAR_PERIOD: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "25m": timedelta(minutes=25),
    "30m": timedelta(minutes=30),
    "1H": timedelta(hours=1),
    "1h": timedelta(hours=1),
    "1D": timedelta(days=1),
    "1w": timedelta(weeks=1),
}


def bar_is_complete(bar_time: datetime, timeframe: str, now: datetime) -> bool:
    """True iff a bar opened at `bar_time` has fully elapsed as of `now`.

    A bar is stamped at its *open* time, so it is complete only once
    `bar_time + period <= now`. An unrecognized timeframe is treated as
    complete (defensive default — callers only pass timeframes they already
    validated against a known interval map).
    """
    period = _BAR_PERIOD.get(timeframe)
    if period is None:
        return True
    return bar_time + period <= now


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


def _session_open_utc(dt: datetime) -> datetime:
    """Return 09:15 IST (expressed in UTC) on dt's IST trading day.

    225 minutes (03:45 UTC) past the UTC calendar-day start that contains dt's IST
    session. During session hours (03:45-10:00 UTC) the IST trading day and the UTC
    calendar day coincide, so truncating dt to its UTC day start and adding 225 minutes
    lands on the correct session open.
    """
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    total_minutes = int(dt.timestamp() // 60)
    utc_day_start_min = (total_minutes // (24 * 60)) * (24 * 60)
    return epoch + timedelta(minutes=utc_day_start_min + _SESSION_OPEN_MIN_OF_DAY - _IST_OFFSET_MINUTES)


def _bar_boundary(dt: datetime, tf_minutes: int) -> datetime:
    """Truncate dt to the nearest tf_minutes boundary, anchored to the session open.

    Anchoring to 09:15 IST (not the Unix epoch) means the bucket containing the first
    tick of a session always starts exactly at the session open, for every timeframe.
    5m/15m already coincided with the epoch grid (225 min divides evenly by both) so
    this is a no-op for them; 25m/30m/1H move onto the session grid.
    """
    session_open = _session_open_utc(dt)
    delta_minutes = int((dt - session_open).total_seconds() // 60)
    truncated_minutes = (delta_minutes // tf_minutes) * tf_minutes
    return session_open + timedelta(minutes=truncated_minutes)


def _in_session_window(dt: datetime, holiday_set: frozenset[date] = frozenset()) -> bool:
    """True iff dt falls in [09:15:00, 15:30:00) IST *and* its IST date is a trading day.

    The clock-time check is integer arithmetic only. The trading-day check (weekday + not
    in holiday_set) only runs once the cheap clock check has already passed, so the hot
    path cost for the overwhelming majority of in-window ticks (real trading days) is
    unchanged; the extra work only happens for the rare tick that also needs the calendar
    check. Without this, a stale/heartbeat print delivered during nominal session hours on
    a weekend or holiday (weekday-holiday awareness lives in `pdp.options.gap_backfill`,
    same as `BarSessionScheduler`'s flush gate) would otherwise be aggregated and persisted
    as if it were real trading data.
    """
    total_minutes_ist = int(dt.timestamp() // 60) + _IST_OFFSET_MINUTES
    minute_of_day = total_minutes_ist % (24 * 60)
    if not (_SESSION_OPEN_MIN_OF_DAY <= minute_of_day < _SESSION_CLOSE_MIN_OF_DAY):
        return False
    ist_date = _ist_date(dt)
    return ist_date.weekday() < 5 and ist_date not in holiday_set


def _ist_date(dt: datetime) -> date:
    """Return dt's IST calendar date."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    total_minutes_ist = int(dt.timestamp() // 60) + _IST_OFFSET_MINUTES
    ist_day_start_min = (total_minutes_ist // (24 * 60)) * (24 * 60)
    return (epoch + timedelta(minutes=ist_day_start_min)).date()


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


def _bar_boundary_1w(dt: datetime) -> datetime:
    """Return the ISO-week start (Monday 00:00 IST, expressed in UTC) for a UTC datetime.

    Monday 00:00 IST = Sunday 18:30 UTC. All NSE session bars in the same ISO week
    share the same 1w bucket. Rolling occurs on the first bar of each new ISO week.
    """
    # Convert to IST minutes-since-epoch
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    total_minutes_ist = int(dt.timestamp() // 60) + _IST_OFFSET_MINUTES
    # IST day boundary and ISO weekday (0=Monday)
    ist_day_start_min = (total_minutes_ist // (24 * 60)) * (24 * 60)
    # Approximate IST date from minutes
    ist_date = (epoch + timedelta(minutes=ist_day_start_min)).date()
    # Monday of that ISO week
    iso_monday = ist_date - timedelta(days=ist_date.weekday())
    # Monday 00:00 IST → UTC (subtract IST offset)
    monday_utc_min = (
        int(datetime(iso_monday.year, iso_monday.month, iso_monday.day, tzinfo=UTC).timestamp() // 60)
        - _IST_OFFSET_MINUTES
    )
    return epoch + timedelta(minutes=monday_utc_min)


class BarBuilder:
    """Accumulates ticks for one (security_id, timeframe) into OHLCV bars."""

    __slots__ = (
        "_bar_time",
        "_close",
        "_high",
        "_is_daily",
        "_is_weekly",
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
        self._is_weekly = timeframe == "1w"
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
            _bar_boundary_1w(effective_dt)
            if self._is_weekly
            else _bar_boundary_1d(effective_dt)
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

    def flush(self) -> BarClosed | None:
        """Force-close the current bar without waiting for a boundary-crossing tick.

        Called at session end (15:30 IST) so the final bucket of the day is emitted even
        when no further tick ever arrives to trigger the usual boundary-crossing close.
        """
        if self._bar_time is None:
            return None
        closed = self._snapshot()
        self._bar_time = None
        return closed

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


def rollup_1m_bars(bars_1m: list[BarClosed], tf_minutes: int, tf_label: str) -> list[BarClosed]:
    """Roll up chronologically-ordered 1-minute ``BarClosed`` bars into ``tf_minutes``
    buckets, anchored via ``_bar_boundary`` — the same session-anchored bucket function
    the live ``BarAggregator`` uses. Shared by ``scripts/oneoff/rebuild_market_bars.py``
    (rebuilding stored index bars) and the on-demand option-strike indicator suite
    (``indicator-matrix-kite-parity``'s NIFTY ATM CE/PE rows, which read 1m ``option_bars``
    that were never fed through the live ``BarAggregator``) — one rollup implementation
    for both callers.
    """
    buckets: dict[datetime, list[BarClosed]] = {}
    for bar in bars_1m:
        bar_time = bar.bar_time if bar.bar_time.tzinfo else bar.bar_time.replace(tzinfo=UTC)
        boundary = _bar_boundary(bar_time, tf_minutes)
        buckets.setdefault(boundary, []).append(bar)

    out: list[BarClosed] = []
    for boundary in sorted(buckets):
        group = sorted(buckets[boundary], key=lambda b: b.bar_time)
        out.append(
            BarClosed(
                security_id=group[0].security_id,
                timeframe=tf_label,
                bar_time=boundary,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
                oi=group[-1].oi,
            )
        )
    return out


class BarAggregator:
    """
    Holds one BarBuilder per (security_id, timeframe).
    Builders are created lazily on first tick.
    """

    def __init__(
        self,
        timeframes: list[str] | None = None,
        holiday_set: frozenset[date] | None = None,
    ) -> None:
        self._timeframes = timeframes or list(_TIMEFRAMES.keys())
        self._builders: dict[tuple[str, str], BarBuilder] = {}
        self._holiday_set = holiday_set or frozenset()

    def push(self, tick: Tick) -> list[BarClosed]:
        """Push a tick to all active timeframe builders; return any closed bars.

        Ticks outside the trading session window ([09:15:00, 15:30:00) IST) are dropped, as
        are ticks whose IST date is a weekend or an `NSE_HOLIDAYS_JSON` holiday — no pre-open,
        post-close, or non-trading-day print contributes to any bar, on any timeframe.
        """
        ltt = tick.ltt if tick.ltt.tzinfo else tick.ltt.replace(tzinfo=UTC)
        if not _in_session_window(ltt, self._holiday_set):
            return []

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

    def flush_session(self) -> list[BarClosed]:
        """Force-close every intraday/daily builder's open bar at session end (15:30 IST).

        Call once per trading day from the session-end scheduler so the final bucket of
        the day exists even when the next tick is a day (or a weekend/holiday) away.

        Excludes ``1w`` builders: a weekly bucket spans multiple trading days, so
        force-closing it every day (not just on the week's last trading day) would
        flush+reset the in-progress week's accumulated OHLCV after a single day, and
        the next day's first tick would then start a fresh bar for the *same* bucket
        timestamp (`_bar_boundary_1w` is Monday-anchored regardless of which weekday
        it's called from) — each day's flush overwriting the last via
        `BarWriter._flush`'s delete-then-insert, so only the final trading day's OHLCV
        would ever survive as that week's persisted bar. The weekly builder's own
        natural boundary-crossing check in `push()` already closes and emits a
        complete week's bar the moment a genuine new week's first tick arrives —
        no forced flush is needed or correct for it.
        """
        closed: list[BarClosed] = []
        for (_, tf), builder in self._builders.items():
            if tf == "1w":
                continue
            bar = builder.flush()
            if bar is not None:
                closed.append(bar)
        return closed
