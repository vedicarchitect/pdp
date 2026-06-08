"""Unit tests for strike resolution helpers."""
from __future__ import annotations

from pdp.strategy.strikes import atm_strike, otm_strike


def test_atm_rounds_to_grid():
    assert atm_strike(22513, 50) == 22500
    assert atm_strike(22526, 50) == 22550
    assert atm_strike(22499, 50) == 22500
    assert atm_strike(22524, 50) == 22500
    assert atm_strike(22550, 100) == 22600  # banker's rounding: 225.5 -> 226


def test_otm_pe_is_below_spot():
    # ATM ~ 22500; OTM-1 PE = 22450
    assert otm_strike(22500, "PE", 1, 50) == 22450
    assert otm_strike(22500, "PE", 2, 50) == 22400


def test_otm_ce_is_above_spot():
    assert otm_strike(22500, "CE", 1, 50) == 22550
    assert otm_strike(22500, "CE", 2, 50) == 22600


def test_otm_case_insensitive():
    assert otm_strike(22500, "pe", 1, 50) == 22450
    assert otm_strike(22500, "ce", 1, 50) == 22550
