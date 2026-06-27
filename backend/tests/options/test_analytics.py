"""Unit tests for max-pain, PCR, and GEX computation."""
from __future__ import annotations

import pytest

from pdp.options.analytics import compute_gex, compute_max_pain, compute_pcr


def _strike(strike: int, ce_oi: int, pe_oi: int) -> dict:
    return {"strike": strike, "ce": {"oi": ce_oi}, "pe": {"oi": pe_oi}}


def test_compute_pcr_known_values():
    strikes = [
        _strike(22000, ce_oi=800_000, pe_oi=1_000_000),
        _strike(22500, ce_oi=0, pe_oi=0),
    ]
    pcr = compute_pcr(strikes)
    assert pcr == pytest.approx(1.25, rel=1e-4)


def test_compute_pcr_zero_call_oi_returns_none():
    strikes = [_strike(22000, ce_oi=0, pe_oi=500_000)]
    assert compute_pcr(strikes) is None


def test_compute_pcr_empty():
    assert compute_pcr([]) is None


def test_compute_max_pain():
    # Three strikes; OI concentrated as CEs at 22500 and PEs at 22000
    # Writers of CEs at 22500 lose most if price closes above 22500
    # Writers of PEs at 22000 lose most if price closes below 22000
    # Minimum pain point should be somewhere between
    strikes = [
        _strike(21500, ce_oi=100_000, pe_oi=500_000),
        _strike(22000, ce_oi=200_000, pe_oi=1_000_000),
        _strike(22500, ce_oi=1_500_000, pe_oi=100_000),
        _strike(23000, ce_oi=800_000, pe_oi=50_000),
    ]
    mp = compute_max_pain(strikes)
    assert mp in [21500, 22000, 22500, 23000]


def test_compute_max_pain_empty():
    assert compute_max_pain([]) is None


# --- GEX tests ---

def _gex_strike(strike: int, ce_gamma: float, ce_oi: int, pe_gamma: float, pe_oi: int) -> dict:
    return {"strike": strike, "ce": {"oi": ce_oi, "gamma": ce_gamma}, "pe": {"oi": pe_oi, "gamma": pe_gamma}}


def test_compute_gex_single_strike():
    # GEX = (0.002 × 100000 - 0.001 × 80000) × 75 × 22500²
    # = 120 × 75 × 506250000 = 4556250000000
    strikes = [_gex_strike(22500, 0.002, 100_000, 0.001, 80_000)]
    result = compute_gex(strikes, lot_size=75, spot=22500.0)
    assert result["per_strike"][0]["strike"] == 22500
    assert result["per_strike"][0]["gex"] == pytest.approx(4_556_250_000_000)
    assert result["net_gex"] == pytest.approx(4_556_250_000_000)


def test_compute_gex_missing_gamma_defaults_to_zero():
    strikes = [{"strike": 22000, "ce": {"oi": 100_000}, "pe": {"oi": 50_000}}]
    result = compute_gex(strikes, lot_size=75, spot=22000.0)
    assert result["per_strike"][0]["gex"] == 0.0
    assert result["net_gex"] == 0.0


def test_compute_gex_net_sum():
    strikes = [
        _gex_strike(22000, 0.001, 100_000, 0.002, 50_000),
        _gex_strike(22500, 0.003, 80_000, 0.001, 60_000),
    ]
    result = compute_gex(strikes, lot_size=75, spot=22000.0)
    per = result["per_strike"]
    assert result["net_gex"] == pytest.approx(per[0]["gex"] + per[1]["gex"])


def test_compute_gex_empty():
    result = compute_gex([], lot_size=75, spot=22000.0)
    assert result["per_strike"] == []
    assert result["net_gex"] == 0.0
