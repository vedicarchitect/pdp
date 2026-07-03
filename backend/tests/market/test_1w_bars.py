"""Unit tests: 1w bar ISO-week boundary rollup + weekly Camarilla seeding."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

from pdp.market.bars import BarAggregator, _bar_boundary_1w
from pdp.market.models import Tick


def _tick(ltp: str, ltt: str, volume: int = 10, sid: str = "13") -> Tick:
    return Tick(
        security_id=sid,
        exchange_segment="IDX_I",
        ltp=Decimal(ltp),
        ltt=datetime.fromisoformat(ltt).replace(tzinfo=UTC),
        volume=volume,
        oi=0,
        ts_recv=time.monotonic(),
    )


# ISO-week boundaries (UTC):
#   Monday 2026-06-22 00:00 IST = 2026-06-21 18:30 UTC  (week of Jun 22)
#   Monday 2026-06-29 00:00 IST = 2026-06-28 18:30 UTC  (week of Jun 29)
_WEEK_JUN22_UTC = datetime(2026, 6, 21, 18, 30, tzinfo=UTC)
_WEEK_JUN29_UTC = datetime(2026, 6, 28, 18, 30, tzinfo=UTC)


def test_1w_boundary_monday_ist() -> None:
    """Monday 2026-06-29 09:15 IST falls in the Jun-29 week bucket."""
    # Monday 2026-06-29 09:15 IST = 2026-06-29 03:45 UTC
    boundary = _bar_boundary_1w(datetime(2026, 6, 29, 3, 45, tzinfo=UTC))
    assert boundary == _WEEK_JUN29_UTC


def test_1w_boundary_friday_same_week() -> None:
    """Friday 2026-07-03 is still in the Jun-29 week bucket."""
    # Friday 2026-07-03 15:30 IST = 2026-07-03 10:00 UTC
    boundary = _bar_boundary_1w(datetime(2026, 7, 3, 10, 0, tzinfo=UTC))
    assert boundary == _WEEK_JUN29_UTC


def test_1w_boundary_prior_friday_in_prev_week() -> None:
    """Friday 2026-06-26 is in the Jun-22 week (not Jun-29)."""
    boundary = _bar_boundary_1w(datetime(2026, 6, 26, 10, 0, tzinfo=UTC))
    assert boundary == _WEEK_JUN22_UTC


def test_1w_bar_rolls_across_week_boundary() -> None:
    """Ticks in week of Jun 22 then Jun 29 produce exactly one closed 1w bar."""
    agg = BarAggregator(timeframes=["1w"])
    closed: list = []

    # Three ticks in week of Jun 22 (Mon-Fri)
    for ltt in ["2026-06-22T03:45:00", "2026-06-24T05:00:00", "2026-06-26T09:00:00"]:
        closed.extend(agg.push(_tick("24000.00", ltt, volume=100)))

    assert closed == [], "no bar should close within the same week"

    # Tick on Monday Jun 29 crosses into next week → Jun-22-week bar closes
    closed.extend(agg.push(_tick("24300.00", "2026-06-29T03:45:00", volume=50)))

    assert len(closed) == 1
    bar = closed[0]
    assert bar.timeframe == "1w"
    assert bar.bar_time == _WEEK_JUN22_UTC
    assert bar.volume == 300  # sum of the 3 ticks (not the Jun-29 tick)


def test_1w_ohlcv_accumulates_correctly() -> None:
    """OHLCV correctly accumulated across multiple ticks in same week."""
    agg = BarAggregator(timeframes=["1w"])

    # Mon/Tue/Wed/Thu of Jun-22 week
    ticks = [
        ("24100", "2026-06-22T03:45:00", 100),
        ("24350", "2026-06-23T03:45:00", 100),
        ("23950", "2026-06-24T03:45:00", 100),
        ("24200", "2026-06-25T03:45:00", 100),
    ]
    for price, ltt, vol in ticks:
        agg.push(_tick(price, ltt, volume=vol))

    # Force close with next week tick
    closed: list = []
    closed.extend(agg.push(_tick("24250", "2026-06-29T03:45:00", volume=50)))

    assert len(closed) == 1
    bar = closed[0]
    assert bar.open == Decimal("24100")
    assert bar.high == Decimal("24350")
    assert bar.low == Decimal("23950")
    assert bar.close == Decimal("24200")
    assert bar.volume == 400
