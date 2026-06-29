"""Unit tests for broker-order-safety: MarginService helpers + preflight."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pdp.orders.margin import (
    _normalise_success_response,
    _parse_basket_margin_response,
)
from pdp.orders.models import PreflightResult


# ── _normalise_success_response ──────────────────────────────────────────────

def test_normalise_success_passes_through_ok_response():
    resp = {"status": "success", "totalMargin": "12345.00"}
    out = _normalise_success_response(resp)
    assert out["totalMargin"] == "12345.00"


def test_normalise_success_raises_on_failure_status():
    resp = {
        "status": "failure",
        "errorType": "InsufficientFunds",
        "errorMessage": "Not enough funds",
    }
    with pytest.raises(ValueError, match="InsufficientFunds"):
        _normalise_success_response(resp)


def test_normalise_success_raises_on_non_dict():
    with pytest.raises(ValueError, match="unexpected"):
        _normalise_success_response("oops")


def test_normalise_success_passes_no_status():
    # Some SDK versions omit status on success
    resp = {"totalMargin": 5000.0}
    out = _normalise_success_response(resp)
    assert out == resp


# ── _parse_basket_margin_response ─────────────────────────────────────────────

def test_parse_basket_margin_top_level_camel():
    data = {"status": "success", "totalMargin": "27500.5"}
    assert _parse_basket_margin_response(data) == Decimal("27500.5")


def test_parse_basket_margin_top_level_snake():
    data = {"total_margin": "18000.00"}
    assert _parse_basket_margin_response(data) == Decimal("18000.00")


def test_parse_basket_margin_nested_dict():
    data = {"data": {"totalMargin": 9999.99}}
    assert _parse_basket_margin_response(data) == Decimal("9999.99")


def test_parse_basket_margin_nested_list():
    data = {"data": [{"margin": 5000}, {"margin": 7000}]}
    assert _parse_basket_margin_response(data) == Decimal("12000")


def test_parse_basket_margin_empty_returns_zero():
    assert _parse_basket_margin_response({}) == Decimal("0")


# ── PreflightResult ──────────────────────────────────────────────────────────

def test_preflight_result_defaults():
    pf = PreflightResult()
    assert pf.ok is True
    assert pf.violations == []
    assert pf.margin_required == Decimal("0")
    assert pf.charge_estimate == Decimal("0")


def test_preflight_result_with_violations():
    pf = PreflightResult(ok=False, violations=["qty not a multiple of lot_size 75"])
    assert not pf.ok
    assert len(pf.violations) == 1
