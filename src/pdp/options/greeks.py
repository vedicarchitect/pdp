"""IV and Greeks computation via vollib + numpy vectorisation."""
from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import polars as pl

_IV_LO = 0.01
_IV_HI = 5.0


def _safe_iv(price: float, spot: float, strike: float, t: float, r: float, flag: str) -> float:
    try:
        from vollib.black_scholes_merton.implied_volatility import implied_volatility
        v = implied_volatility(price, spot, strike, t, r, 0.0, flag)
        if np.isnan(v) or np.isinf(v) or v <= 0:
            return _IV_LO
        return float(np.clip(v, _IV_LO, _IV_HI))
    except Exception:
        return _IV_LO


def _safe_greek(greek_fn, flag: str, spot: float, strike: float, t: float, r: float, iv: float) -> float:  # type: ignore[no-untyped-def]
    try:
        v = greek_fn(flag, spot, strike, t, r, iv, 0.0)
        return 0.0 if (np.isnan(v) or np.isinf(v)) else float(v)
    except Exception:
        return 0.0


def compute_greeks(
    strikes_df: pl.DataFrame,
    spot: float,
    expiry_date: date,
    risk_free_rate: float,
) -> pl.DataFrame:
    """Add iv/delta/gamma/theta/vega columns to a strikes DataFrame.

    Input columns: strike (float), ce_ltp (float), pe_ltp (float).
    Returns the same rows with added Greek columns for CE and PE.
    If T <= 0 all Greeks are zeroed.
    """
    today = datetime.now(UTC).date()
    t = (expiry_date - today).days / 365.0

    n = len(strikes_df)
    zero = lambda: [0.0] * n  # noqa: E731

    if t <= 0:
        return strikes_df.with_columns(
            ce_iv=pl.Series(zero()),
            ce_delta=pl.Series(zero()),
            ce_gamma=pl.Series(zero()),
            ce_theta=pl.Series(zero()),
            ce_vega=pl.Series(zero()),
            pe_iv=pl.Series(zero()),
            pe_delta=pl.Series(zero()),
            pe_gamma=pl.Series(zero()),
            pe_theta=pl.Series(zero()),
            pe_vega=pl.Series(zero()),
        )

    from vollib.black_scholes_merton.greeks.analytical import delta, gamma, theta, vega

    strikes = strikes_df["strike"].to_list()
    ce_ltps = strikes_df["ce_ltp"].to_list()
    pe_ltps = strikes_df["pe_ltp"].to_list()

    ce_iv_arr, pe_iv_arr = [], []
    ce_delta_arr, ce_gamma_arr, ce_theta_arr, ce_vega_arr = [], [], [], []
    pe_delta_arr, pe_gamma_arr, pe_theta_arr, pe_vega_arr = [], [], [], []

    for k, ce_price, pe_price in zip(strikes, ce_ltps, pe_ltps, strict=True):
        iv_c = _safe_iv(ce_price, spot, k, t, risk_free_rate, "c")
        iv_p = _safe_iv(pe_price, spot, k, t, risk_free_rate, "p")
        ce_iv_arr.append(iv_c)
        pe_iv_arr.append(iv_p)
        ce_delta_arr.append(_safe_greek(delta, "c", spot, k, t, risk_free_rate, iv_c))
        ce_gamma_arr.append(_safe_greek(gamma, "c", spot, k, t, risk_free_rate, iv_c))
        ce_theta_arr.append(_safe_greek(theta, "c", spot, k, t, risk_free_rate, iv_c))
        ce_vega_arr.append(_safe_greek(vega, "c", spot, k, t, risk_free_rate, iv_c))
        pe_delta_arr.append(_safe_greek(delta, "p", spot, k, t, risk_free_rate, iv_p))
        pe_gamma_arr.append(_safe_greek(gamma, "p", spot, k, t, risk_free_rate, iv_p))
        pe_theta_arr.append(_safe_greek(theta, "p", spot, k, t, risk_free_rate, iv_p))
        pe_vega_arr.append(_safe_greek(vega, "p", spot, k, t, risk_free_rate, iv_p))

    return strikes_df.with_columns(
        ce_iv=pl.Series(ce_iv_arr),
        ce_delta=pl.Series(ce_delta_arr),
        ce_gamma=pl.Series(ce_gamma_arr),
        ce_theta=pl.Series(ce_theta_arr),
        ce_vega=pl.Series(ce_vega_arr),
        pe_iv=pl.Series(pe_iv_arr),
        pe_delta=pl.Series(pe_delta_arr),
        pe_gamma=pl.Series(pe_gamma_arr),
        pe_theta=pl.Series(pe_theta_arr),
        pe_vega=pl.Series(pe_vega_arr),
    )
