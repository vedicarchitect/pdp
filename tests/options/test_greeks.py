"""Unit tests for options greeks computation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from pdp.options.greeks import _IV_LO, compute_greeks


def _df(strikes: list[float], ce_ltps: list[float], pe_ltps: list[float]) -> pl.DataFrame:
    return pl.DataFrame({"strike": strikes, "ce_ltp": ce_ltps, "pe_ltp": pe_ltps})


def test_atm_strike_returns_nonzero_greeks():
    spot = 22500.0
    expiry = (datetime.now(UTC).date() + timedelta(days=10))
    df = _df([22500.0], [200.0], [200.0])

    result = compute_greeks(df, spot, expiry, 0.065)

    assert result["ce_iv"][0] > 0
    assert result["ce_delta"][0] > 0
    assert result["pe_delta"][0] < 0
    assert result["ce_gamma"][0] > 0
    assert result["ce_vega"][0] > 0


def test_expired_expiry_returns_all_zero():
    spot = 22500.0
    expiry = datetime.now(UTC).date() - timedelta(days=1)  # past expiry
    df = _df([22500.0], [100.0], [100.0])

    result = compute_greeks(df, spot, expiry, 0.065)

    assert result["ce_iv"][0] == 0.0
    assert result["ce_delta"][0] == 0.0
    assert result["pe_delta"][0] == 0.0
    assert result["ce_gamma"][0] == 0.0


def test_deep_otm_nan_clamped():
    """Deep OTM options with near-zero price should have IV clamped to _IV_LO."""
    spot = 22500.0
    expiry = datetime.now(UTC).date() + timedelta(days=5)
    # Deep OTM CE: strike 30000 with tiny price → IV solver likely returns NaN
    df = _df([30000.0], [0.05], [0.05])

    result = compute_greeks(df, spot, expiry, 0.065)

    # IV must be within valid range (clamped, not NaN)
    ce_iv = result["ce_iv"][0]
    assert not (ce_iv != ce_iv)  # not NaN
    assert ce_iv >= _IV_LO
