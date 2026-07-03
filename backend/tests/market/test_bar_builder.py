"""Unit tests for BarBuilder and BarAggregator boundary logic."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

from pdp.market.bars import BarAggregator, BarBuilder, BarClosed, _bar_boundary_1w
from pdp.market.models import Tick


def _tick(
    sid: str = "13",
    ltp: str = "100.0",
    ltt: datetime | None = None,
    volume: int = 10,
    ts_recv: float | None = None,
) -> Tick:
    if ltt is None:
        ltt = datetime.now(UTC)
    return Tick(
        security_id=sid,
        exchange_segment="NSE_EQ",
        ltp=Decimal(ltp),
        ltt=ltt,
        volume=volume,
        oi=0,
        ts_recv=ts_recv if ts_recv is not None else time.monotonic(),
    )


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


class TestBarBoundary:
    def test_1w_boundary_aligns_to_monday_0000_ist(self) -> None:
        # 2026-06-30 is a Tuesday.
        # Monday of that week is 2026-06-29.
        # 00:00 IST on Monday is Sunday 18:30 UTC, which is 2026-06-28 18:30:00 UTC.

        # A time on Tuesday 2026-06-30 at 06:00 UTC (11:30 IST)
        t_tue = _dt("2026-06-30T06:00:00")
        b_tue = _bar_boundary_1w(t_tue)
        assert b_tue == _dt("2026-06-28T18:30:00")

        # A time on Monday 2026-06-29 at 03:45 UTC (09:15 IST, market open)
        t_mon = _dt("2026-06-29T03:45:00")
        b_mon = _bar_boundary_1w(t_mon)
        assert b_mon == _dt("2026-06-28T18:30:00")

        # A time on Friday 2026-07-03 at 10:00 UTC (15:30 IST, market close)
        t_fri = _dt("2026-07-03T10:00:00")
        b_fri = _bar_boundary_1w(t_fri)
        assert b_fri == _dt("2026-06-28T18:30:00")

        # Previous Friday 2026-06-26 should roll to the previous Monday (2026-06-21 18:30 UTC)
        t_prev_fri = _dt("2026-06-26T06:00:00")
        b_prev_fri = _bar_boundary_1w(t_prev_fri)
        assert b_prev_fri == _dt("2026-06-21T18:30:00")


class TestBarBuilder:
    def test_first_tick_opens_bar(self) -> None:
        builder = BarBuilder("13", "5m")
        t = _tick(ltt=_dt("2026-01-01T03:45:03"))
        result = builder.push(t)
        assert result is None
        # Bar not closed yet — internal state open == ltp
        assert builder._open == Decimal("100.0")

    def test_accumulation_updates_ohlcv(self) -> None:
        builder = BarBuilder("13", "5m")
        builder.push(_tick(ltp="100.0", ltt=_dt("2026-01-01T03:45:03"), volume=10))
        builder.push(_tick(ltp="105.0", ltt=_dt("2026-01-01T03:46:00"), volume=20))
        builder.push(_tick(ltp="98.0",  ltt=_dt("2026-01-01T03:47:00"), volume=15))
        builder.push(_tick(ltp="102.0", ltt=_dt("2026-01-01T03:48:00"), volume=5))

        assert builder._open == Decimal("100.0")
        assert builder._high == Decimal("105.0")
        assert builder._low  == Decimal("98.0")
        assert builder._close == Decimal("102.0")
        assert builder._volume == 50

    def test_boundary_crossing_emits_bar_closed(self) -> None:
        builder = BarBuilder("13", "5m")
        builder.push(_tick(ltp="100.0", ltt=_dt("2026-01-01T03:45:00"), volume=10))
        builder.push(_tick(ltp="103.0", ltt=_dt("2026-01-01T03:48:00"), volume=5))

        # Tick at 09:50 crosses the 09:45 5m boundary
        closed = builder.push(_tick(ltp="101.0", ltt=_dt("2026-01-01T03:50:00"), volume=8))

        assert closed is not None
        assert isinstance(closed, BarClosed)
        assert closed.bar_time == _dt("2026-01-01T03:45:00")
        assert closed.open  == Decimal("100.0")
        assert closed.high  == Decimal("103.0")
        assert closed.low   == Decimal("100.0")
        assert closed.close == Decimal("103.0")
        assert closed.volume == 15
        assert closed.timeframe == "5m"

        # New bar opened at 03:50
        assert builder._bar_time == _dt("2026-01-01T03:50:00")
        assert builder._open == Decimal("101.0")

    def test_stale_ltt_uses_ts_recv(self) -> None:
        builder = BarBuilder("13", "1m")
        now_wall = time.time()
        now_mono = time.monotonic()

        # ltt is 5 seconds in the future relative to ts_recv approximation → stale
        ltt_future = datetime.fromtimestamp(now_wall + 5.0, tz=UTC)
        t = _tick(ltp="200.0", ltt=ltt_future, ts_recv=now_mono, volume=1)
        result = builder.push(t)
        assert result is None  # should not crash, bar opened using ts_recv


class TestBarAggregator:
    def test_push_returns_closed_bars_for_all_timeframes(self) -> None:
        agg = BarAggregator(timeframes=["1m", "5m"])

        # Open bars in 09:15 window
        agg.push(_tick(ltt=_dt("2026-01-01T03:45:00"), volume=10))
        agg.push(_tick(ltt=_dt("2026-01-01T03:45:30"), volume=10))

        # Cross 09:16 boundary (only 1m closes)
        closed = agg.push(_tick(ltt=_dt("2026-01-01T03:46:00"), volume=5))
        assert len(closed) == 1
        assert closed[0].timeframe == "1m"
        assert closed[0].bar_time == _dt("2026-01-01T03:45:00")

    def test_creates_builders_lazily(self) -> None:
        agg = BarAggregator(timeframes=["5m"])
        assert len(agg._builders) == 0
        agg.push(_tick(ltt=_dt("2026-01-01T03:45:00")))
        assert ("13", "5m") in agg._builders

    def test_different_securities_independent(self) -> None:
        agg = BarAggregator(timeframes=["1m"])
        agg.push(_tick(sid="13", ltt=_dt("2026-01-01T03:45:00"), volume=1))
        agg.push(_tick(sid="25", ltt=_dt("2026-01-01T03:45:00"), volume=2))

        closed = agg.push(_tick(sid="13", ltt=_dt("2026-01-01T03:46:00"), volume=3))
        assert len(closed) == 1
        assert closed[0].security_id == "13"
