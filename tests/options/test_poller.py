"""Unit tests for OptionsChainPoller market-hours guard and hub overflow."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pdp.options.poller import _in_market_hours


def _ist(hour: int, minute: int) -> datetime:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime(2026, 6, 6, hour, minute, 0, tzinfo=ist)


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (9, 15, True),   # exact open
        (12, 0, True),   # mid-session
        (15, 35, True),  # exact close
        (9, 14, False),  # one minute before open
        (15, 36, False), # one minute after close
        (8, 0, False),   # before market
        (16, 0, False),  # after market
    ],
)
def test_in_market_hours(hour: int, minute: int, expected: bool) -> None:
    mock_dt = _ist(hour, minute)
    with patch("pdp.options.poller._ist_now", return_value=mock_dt):
        assert _in_market_hours() == expected
