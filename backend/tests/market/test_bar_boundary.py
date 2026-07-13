"""Session-anchored bar boundary tests (bar-session-anchoring).

Written before the fix: the anchoring tests fail against the epoch-anchored
``_bar_boundary`` for every timeframe that doesn't evenly divide 225 (minutes from UTC
midnight to 03:45 UTC / 09:15 IST) — i.e. 25m/30m/1H. The session-window and flush tests
fail with an ImportError/AttributeError until ``_in_session_window``/``flush_session`` exist.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pdp.market.bars import (
    BarAggregator,
    _bar_boundary,
    _bar_boundary_1d,
    _bar_boundary_1w,
)
from pdp.market.models import Tick


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def _tick(sid: str = "13", ltp: str = "100.0", ltt: datetime | None = None, volume: int = 10) -> Tick:
    import time

    return Tick(
        security_id=sid,
        exchange_segment="NSE_EQ",
        ltp=Decimal(ltp),
        ltt=ltt if ltt is not None else datetime.now(UTC),
        volume=volume,
        oi=0,
        ts_recv=time.monotonic(),
    )


# Four consecutive trading days (Mon-Thu), each tick at the session-open instant (03:45 UTC = 09:15 IST).
_SESSION_OPEN_TICKS = {
    "2026-06-29-monday": "2026-06-29T03:45:00",
    "2026-06-30-tuesday": "2026-06-30T03:45:00",
    "2026-07-01-wednesday": "2026-07-01T03:45:00",
    "2026-07-02-thursday": "2026-07-02T03:45:00",
}

_INTRADAY_TFS = {"5m": 5, "15m": 15, "25m": 25, "30m": 30, "1H": 60}


class TestSessionOpenAnchoring:
    @pytest.mark.parametrize("day_label,session_open_iso", list(_SESSION_OPEN_TICKS.items()))
    @pytest.mark.parametrize("tf_label,tf_minutes", list(_INTRADAY_TFS.items()))
    def test_session_open_tick_starts_its_own_bucket(
        self, tf_label: str, tf_minutes: int, day_label: str, session_open_iso: str
    ) -> None:
        tick_dt = _dt(session_open_iso)
        boundary = _bar_boundary(tick_dt, tf_minutes)
        assert boundary == tick_dt, f"{tf_label} on {day_label}: bucket should start at the session open"

    def test_25m_does_not_drift_across_days(self) -> None:
        # Pre-fix this walks 09:15 / 09:00 / 09:10 / 08:55 across four consecutive days.
        for session_open_iso in _SESSION_OPEN_TICKS.values():
            tick_dt = _dt(session_open_iso)
            assert _bar_boundary(tick_dt, 25) == tick_dt

    def test_5m_15m_boundaries_unchanged_from_epoch_anchoring(self) -> None:
        """5m/15m already coincide with the session grid — this is the no-op regression check."""

        def _epoch_boundary(dt: datetime, tf_minutes: int) -> datetime:
            epoch = datetime(1970, 1, 1, tzinfo=UTC)
            total_minutes = int((dt - epoch).total_seconds() // 60)
            return epoch + timedelta(minutes=(total_minutes // tf_minutes) * tf_minutes)

        probe_times = [
            "2026-06-29T03:45:00",
            "2026-06-29T05:37:12",
            "2026-06-29T09:59:47",
            "2026-06-30T04:12:33",
            "2026-07-01T07:03:01",
            "2026-07-02T09:29:59",
        ]
        for iso in probe_times:
            dt = _dt(iso)
            for tf_minutes in (5, 15):
                assert _bar_boundary(dt, tf_minutes) == _epoch_boundary(dt, tf_minutes), (
                    f"{tf_minutes}m boundary moved for {iso} — should be unchanged"
                )

    def test_1d_1w_boundaries_unchanged(self) -> None:
        # 1D: IST calendar-day start expressed in UTC.
        assert _bar_boundary_1d(_dt("2026-06-29T03:45:00")) == _dt("2026-06-28T18:30:00")  # Monday session
        assert _bar_boundary_1d(_dt("2026-06-30T09:59:00")) == _dt("2026-06-29T18:30:00")  # Tuesday session
        # 1w: Monday 00:00 IST start expressed in UTC (matches test_bar_builder.py's existing cases).
        assert _bar_boundary_1w(_dt("2026-06-30T06:00:00")) == _dt("2026-06-28T18:30:00")
        assert _bar_boundary_1w(_dt("2026-07-03T10:00:00")) == _dt("2026-06-28T18:30:00")

    def test_monday_after_friday_holiday_anchors_on_monday_open(self) -> None:
        # 2026-07-06 is a Monday; whatever happened the preceding Friday (holiday or not)
        # is irrelevant — the boundary is a pure function of the tick's own IST trading day.
        monday_open = _dt("2026-07-06T03:45:00")
        for tf_minutes in _INTRADAY_TFS.values():
            assert _bar_boundary(monday_open, tf_minutes) == monday_open


class TestSessionWindow:
    def test_pre_open_tick_914_59_produces_no_bar(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        closed = agg.push(_tick(ltt=_dt("2026-06-29T03:44:59")))  # 09:14:59 IST
        assert closed == []
        assert ("13", "1m") not in agg._builders

    def test_open_tick_915_00_is_included(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        agg.push(_tick(ltt=_dt("2026-06-29T03:45:00")))  # 09:15:00 IST
        assert ("13", "1m") in agg._builders

    def test_close_boundary_tick_1530_00_produces_no_bar(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        closed = agg.push(_tick(ltt=_dt("2026-06-29T10:00:00")))  # 15:30:00 IST
        assert closed == []
        assert ("13", "1m") not in agg._builders

    def test_last_tick_1529_59_is_included(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        agg.push(_tick(ltt=_dt("2026-06-29T09:59:59")))  # 15:29:59 IST
        assert ("13", "1m") in agg._builders

    def test_post_close_tick_produces_no_bar(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        closed = agg.push(_tick(ltt=_dt("2026-06-29T10:05:00")))  # 15:35 IST
        assert closed == []
        assert ("13", "1m") not in agg._builders

    def test_weekend_tick_in_clock_window_produces_no_bar(self) -> None:
        # 2026-07-11 is a Saturday; 03:45 UTC = 09:15 IST, inside the clock window, but not
        # a trading day. A stale/heartbeat print delivered then must not open a bar.
        agg = BarAggregator(timeframes=["1m"])
        closed = agg.push(_tick(ltt=_dt("2026-07-11T03:45:00")))
        assert closed == []
        assert ("13", "1m") not in agg._builders

    def test_holiday_tick_in_clock_window_produces_no_bar(self) -> None:
        # 2026-06-26 is a weekday but a listed NSE holiday.
        agg = BarAggregator(
            timeframes=["1m"], holiday_set=frozenset({_dt("2026-06-26T00:00:00").date()})
        )
        closed = agg.push(_tick(ltt=_dt("2026-06-26T05:00:00")))  # 10:30 IST, in-window
        assert closed == []
        assert ("13", "1m") not in agg._builders

    def test_holiday_set_does_not_reject_other_trading_days(self) -> None:
        agg = BarAggregator(
            timeframes=["1m"], holiday_set=frozenset({_dt("2026-06-26T00:00:00").date()})
        )
        agg.push(_tick(ltt=_dt("2026-06-29T03:45:00")))  # Monday, unaffected
        assert ("13", "1m") in agg._builders


class TestSessionFlush:
    def test_flush_session_closes_the_final_open_bucket(self) -> None:
        agg = BarAggregator(timeframes=["30m"])
        # 09:50 UTC = 15:20 IST; under 09:15-anchored 30m buckets this falls in the last
        # (partial) bucket of the day, 15:15-15:30 IST = 09:45-10:00 UTC.
        agg.push(_tick(ltt=_dt("2026-06-29T09:50:00"), ltp="24500"))
        closed = agg.flush_session()
        assert len(closed) == 1
        assert closed[0].bar_time == _dt("2026-06-29T09:45:00")
        assert closed[0].timeframe == "30m"
        assert closed[0].close == Decimal("24500")

    def test_flush_session_with_no_open_bucket_returns_empty(self) -> None:
        agg = BarAggregator(timeframes=["30m"])
        assert agg.flush_session() == []

    def test_flush_session_lets_the_next_session_open_a_fresh_bar(self) -> None:
        agg = BarAggregator(timeframes=["30m"])
        agg.push(_tick(ltt=_dt("2026-06-29T09:50:00"), ltp="24500"))
        agg.flush_session()
        # Next trading day's session-open tick should open a brand-new bar, not extend
        # the flushed one.
        closed = agg.push(_tick(ltt=_dt("2026-06-30T03:45:00"), ltp="24600"))
        assert closed == []  # first tick of a new bar never closes anything
        builder = agg._builders[("13", "30m")]
        assert builder._bar_time == _dt("2026-06-30T03:45:00")
        assert builder._open == Decimal("24600")

    def test_late_tick_after_flush_reopens_and_re_closes_the_same_bucket(self) -> None:
        """market-bars-duplicate-write-fix root cause: a network-delayed tick whose LTT
        still falls in the bucket `flush_session()` already force-closed reopens that
        exact bucket (BarBuilder.push sees `_bar_time is None` -> "first tick"). The
        *next* tick that crosses a boundary then emits a *second* `BarClosed` for the
        same `(sid, tf, bar_time)` — this is what duplicates `market_bars` writes. The
        write-path fix (delete-then-insert per bucket in `BarWriter._flush`) makes this
        idempotent at the storage layer; this test documents the aggregator-level cause.
        """
        agg = BarAggregator(timeframes=["30m"])
        bucket_start = _dt("2026-06-29T09:45:00")  # 15:15-15:30 IST bucket
        agg.push(_tick(ltt=_dt("2026-06-29T09:50:00"), ltp="24500"))

        first_close = agg.flush_session()
        assert len(first_close) == 1
        assert first_close[0].bar_time == bucket_start

        # A late tick (still inside the session window, LTT before 15:30 IST) arrives
        # after the flush already ran — the builder was reset to `_bar_time is None`,
        # so this is treated as a brand-new "first tick" for the SAME bucket.
        late_tick_closed = agg.push(_tick(ltt=_dt("2026-06-29T09:59:30"), ltp="24550"))
        assert late_tick_closed == []
        builder = agg._builders[("13", "30m")]
        assert builder._bar_time == bucket_start  # reopened the already-flushed bucket

        # The next tick crosses a boundary -> emits a SECOND BarClosed for bucket_start.
        second_close = agg.push(_tick(ltt=_dt("2026-06-30T03:45:00"), ltp="24600"))
        assert len(second_close) == 1
        assert second_close[0].bar_time == bucket_start  # duplicate of first_close[0]

    def test_flush_session_does_not_force_close_the_weekly_builder(self) -> None:
        """flush_session() must skip "1w": force-closing it every day (not just the
        week's last trading day) would flush+reset the in-progress week's OHLCV after
        a single day, and the same Monday-anchored bucket would then be overwritten by
        each subsequent day's single-day data — by Friday only Friday's OHLCV would
        survive as that week's persisted bar. See BarAggregator.flush_session's
        docstring for the full mechanism.
        """
        agg = BarAggregator(timeframes=["1w"])
        agg.push(_tick(ltt=_dt("2026-06-29T03:45:00"), ltp="24500"))  # Monday open
        assert agg.flush_session() == []  # 1w must not be force-closed at day-end
        builder = agg._builders[("13", "1w")]
        assert builder._bar_time is not None  # still accumulating, not reset

        # Tuesday's tick extends the SAME week's bucket rather than starting fresh.
        closed = agg.push(_tick(ltt=_dt("2026-06-30T03:45:00"), ltp="24600"))
        assert closed == []
        assert builder._open == Decimal("24500")  # week's open is still Monday's
        assert builder._close == Decimal("24600")  # extended, not reset

    def test_flush_session_still_closes_daily_and_intraday_builders_alongside_weekly(self) -> None:
        """The 1w exclusion must not regress the existing daily/intraday flush."""
        agg = BarAggregator(timeframes=["30m", "1D", "1w"])
        agg.push(_tick(ltt=_dt("2026-06-29T09:50:00"), ltp="24500"))
        closed = agg.flush_session()
        closed_tfs = {c.timeframe for c in closed}
        assert closed_tfs == {"30m", "1D"}
        assert "1w" not in closed_tfs
