"""Integration tests: fake tick sequence → BarAggregator → BarClosed events."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pdp.market.bars import BarAggregator
from pdp.market.models import Tick


def _tick(ltp: str, ltt: str, volume: int = 10, sid: str = "13") -> Tick:
    import time

    return Tick(
        security_id=sid,
        exchange_segment="NSE_EQ",
        ltp=Decimal(ltp),
        ltt=datetime.fromisoformat(ltt).replace(tzinfo=UTC),
        volume=volume,
        oi=0,
        ts_recv=time.monotonic(),
    )


def test_five_minute_bar_sequence() -> None:
    """Full 5m bar cycle: open, accumulate, close, open next."""
    agg = BarAggregator(timeframes=["5m"])
    closed_bars = []

    ticks = [
        _tick("24500.00", "2026-01-02T03:45:00", volume=100),
        _tick("24510.50", "2026-01-02T03:46:00", volume=200),
        _tick("24480.00", "2026-01-02T03:47:30", volume=150),
        _tick("24495.00", "2026-01-02T03:49:59", volume=50),
        # This tick crosses the 5m boundary → bar at 03:45 closes
        _tick("24520.00", "2026-01-02T03:50:01", volume=80),
    ]
    for t in ticks:
        closed_bars.extend(agg.push(t))

    assert len(closed_bars) == 1
    bar = closed_bars[0]
    assert bar.timeframe == "5m"
    assert bar.bar_time == datetime(2026, 1, 2, 3, 45, 0, tzinfo=UTC)
    assert bar.open  == Decimal("24500.00")
    assert bar.high  == Decimal("24510.50")
    assert bar.low   == Decimal("24480.00")
    assert bar.close == Decimal("24495.00")
    assert bar.volume == 500


def test_multiple_bars_in_sequence() -> None:
    """Two full 1m bars emitted back-to-back."""
    agg = BarAggregator(timeframes=["1m"])
    closed = []

    for iso, ltp in [
        ("2026-01-02T03:45:00", "100"),
        ("2026-01-02T03:45:30", "101"),
        ("2026-01-02T03:46:00", "102"),  # closes 03:45 bar
        ("2026-01-02T03:46:30", "103"),
        ("2026-01-02T03:47:00", "104"),  # closes 03:46 bar
    ]:
        closed.extend(agg.push(_tick(ltp, iso)))

    assert len(closed) == 2
    assert closed[0].bar_time == datetime(2026, 1, 2, 3, 45, tzinfo=UTC)
    assert closed[1].bar_time == datetime(2026, 1, 2, 3, 46, tzinfo=UTC)
    assert closed[0].close == Decimal("101")
    assert closed[1].close == Decimal("103")


def test_no_bars_within_single_window() -> None:
    """No BarClosed events if all ticks stay within one window."""
    agg = BarAggregator(timeframes=["5m"])
    closed = []
    for i in range(10):
        t = _tick(str(100 + i), "2026-01-02T03:45:00")
        closed.extend(agg.push(t))
    assert closed == []
