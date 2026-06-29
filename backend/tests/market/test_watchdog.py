"""Unit tests for feed watchdog: market-hours gate + stale detection."""

from __future__ import annotations

import asyncio
import time as _time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pdp.market.watchdog import FeedWatchdog, _in_market_hours
from pdp.risk.feed_halt import FeedStaleHalt


# ---------------------------------------------------------------------------
# _in_market_hours — pure-function tests (monkeypatched datetime)
# ---------------------------------------------------------------------------

def _ist_time(hour: int, minute: int) -> datetime:
    import zoneinfo
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_in_market_hours_during_session():
    """11:30 IST is inside trading hours (09:15 – 15:35)."""
    with patch("pdp.market.watchdog.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_time(11, 30)
        assert _in_market_hours() is True


def test_in_market_hours_at_open():
    """09:15 IST is exactly at open — inside."""
    with patch("pdp.market.watchdog.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_time(9, 15)
        assert _in_market_hours() is True


def test_in_market_hours_before_open():
    """09:00 IST is before market open — outside."""
    with patch("pdp.market.watchdog.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_time(9, 0)
        assert _in_market_hours() is False


def test_in_market_hours_after_close():
    """16:00 IST is after market close — outside."""
    with patch("pdp.market.watchdog.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_time(16, 0)
        assert _in_market_hours() is False


def test_in_market_hours_at_close():
    """15:35 IST is exactly at close — inside."""
    with patch("pdp.market.watchdog.datetime") as mock_dt:
        mock_dt.now.return_value = _ist_time(15, 35)
        assert _in_market_hours() is True


# ---------------------------------------------------------------------------
# FeedWatchdog stale detection
# ---------------------------------------------------------------------------

def _make_stale_router(age_seconds: float = 200.0) -> MagicMock:
    router = MagicMock()
    router.last_tick_ts = _time.monotonic() - age_seconds
    return router


def _make_fresh_router() -> MagicMock:
    router = MagicMock()
    router.last_tick_ts = _time.monotonic()
    return router


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter._feed = None
    adapter._connected = False
    return adapter


@pytest.mark.asyncio
async def test_watchdog_calls_on_feed_stale_when_age_exceeds_threshold():
    """Watchdog must call FeedStaleHalt.on_feed_stale when tick is too old.

    The watchdog polls every ~1 second (asyncio.wait_for timeout); we wait 1.3s
    so exactly one check cycle completes.
    """
    feed_halt = FeedStaleHalt(halt_after_seconds=999)  # high threshold — won't engage here
    router = _make_stale_router(age_seconds=200)
    adapter = _make_adapter()

    watchdog = FeedWatchdog(router, adapter, stale_seconds=1, feed_halt=feed_halt)

    with patch("pdp.market.watchdog._in_market_hours", return_value=True):
        await watchdog.start()
        await asyncio.sleep(1.3)
        await watchdog.stop()

    assert watchdog._was_stale is True


@pytest.mark.asyncio
async def test_watchdog_skips_stale_check_outside_market_hours():
    """Watchdog must NOT flag a stale tick outside market hours."""
    feed_halt = MagicMock(spec=FeedStaleHalt)
    router = _make_stale_router(age_seconds=200)
    adapter = _make_adapter()

    watchdog = FeedWatchdog(router, adapter, stale_seconds=1, feed_halt=feed_halt)

    with patch("pdp.market.watchdog._in_market_hours", return_value=False):
        await watchdog.start()
        await asyncio.sleep(1.3)
        await watchdog.stop()

    feed_halt.on_feed_stale.assert_not_called()
    assert watchdog._was_stale is False


@pytest.mark.asyncio
async def test_watchdog_notifies_recovery_when_feed_resumes():
    """After a stale period, fresh ticks must trigger on_feed_recovered."""
    feed_halt = MagicMock(spec=FeedStaleHalt)
    router = _make_stale_router(age_seconds=200)
    adapter = _make_adapter()

    watchdog = FeedWatchdog(router, adapter, stale_seconds=1, feed_halt=feed_halt)

    with patch("pdp.market.watchdog._in_market_hours", return_value=True):
        await watchdog.start()
        await asyncio.sleep(1.3)  # one check cycle — becomes stale
        assert watchdog._was_stale is True

        # Feed resumes — update last_tick_ts to now
        router.last_tick_ts = _time.monotonic()
        await asyncio.sleep(1.3)  # second cycle — detects fresh feed
        await watchdog.stop()

    feed_halt.on_feed_recovered.assert_called()
