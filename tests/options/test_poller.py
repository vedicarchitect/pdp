"""Unit tests for OptionsChainPoller market-hours guard and hub overflow."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pdp.options.dhan_client import UNDERLYING_MAP
from pdp.options.poller import _in_market_hours, _parse_chain


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


def test_underlying_security_ids_use_idx_segment() -> None:
    assert UNDERLYING_MAP["NIFTY"] == (13, "IDX_I")
    assert UNDERLYING_MAP["BANKNIFTY"] == (25, "IDX_I")
    # Regression: MIDCPNIFTY must not collide with NIFTY's id (13).
    assert UNDERLYING_MAP["MIDCPNIFTY"] == (442, "IDX_I")
    assert UNDERLYING_MAP["NIFTY"][0] != UNDERLYING_MAP["MIDCPNIFTY"][0]


def _raw_chain(ce: dict, pe: dict, expiry: str = "2099-12-31") -> dict:
    return {
        "data": {"last_price": 22500.0, "oc": {"22500.000000": {"ce": ce, "pe": pe}}},
        "expiry": expiry,
    }


def test_parse_chain_prefers_dhan_greeks() -> None:
    ce = {
        "last_price": 200.0, "oi": 1000, "volume": 50,
        "implied_volatility": 12.5,
        "greeks": {"delta": 0.55, "gamma": 0.002, "theta": -15.2, "vega": 28.5},
    }
    pe = {
        "last_price": 180.0, "oi": 1200, "volume": 40,
        "implied_volatility": 13.0,
        "greeks": {"delta": -0.45, "gamma": 0.002, "theta": -14.0, "vega": 27.0},
    }
    rows = _parse_chain(_raw_chain(ce, pe), "NIFTY", 0.065)
    assert len(rows) == 1
    s = rows[0]
    assert s["strike"] == 22500.0
    assert s["expiry"] == "2099-12-31"
    # IV stored as a decimal (Dhan reports percent).
    assert s["ce"]["iv"] == pytest.approx(0.125)
    assert s["ce"]["delta"] == pytest.approx(0.55)
    assert s["ce"]["oi"] == 1000
    assert s["pe"]["delta"] == pytest.approx(-0.45)


def test_parse_chain_falls_back_to_vollib_when_greeks_missing() -> None:
    # No greeks/iv from Dhan -> vollib computes from LTP for a near-term expiry.
    from datetime import date, timedelta

    expiry = (date.today() + timedelta(days=30)).isoformat()
    ce = {"last_price": 250.0, "oi": 500, "volume": 10}
    pe = {"last_price": 240.0, "oi": 600, "volume": 12}
    rows = _parse_chain(_raw_chain(ce, pe, expiry=expiry), "NIFTY", 0.065)
    s = rows[0]
    assert s["ce"]["iv"] > 0
    assert 0.0 < s["ce"]["delta"] <= 1.0
    assert -1.0 <= s["pe"]["delta"] < 0.0
