"""Unit tests for broker-order-safety: MarginService helpers + preflight."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pdp.orders.margin import (
    MarginService,
    OrderSpec,
    _normalise_success_response,
    _parse_basket_margin_response,
)
from pdp.orders.models import PreflightResult
from pdp.orders.router import _check_lot_freeze


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


# ── _check_lot_freeze (W2 — pure validator extracted from _preflight) ─────────

def test_check_lot_freeze_non_multiple_qty():
    vs = _check_lot_freeze(100, 75, None, {}, "13", "NSE_FNO")
    assert any("not a multiple" in v for v in vs)


def test_check_lot_freeze_exact_multiple_passes():
    assert _check_lot_freeze(75, 75, None, {}, "13", "NSE_FNO") == []


def test_check_lot_freeze_exceeds_instrument_freeze():
    vs = _check_lot_freeze(200, 1, 150, {}, "13", "NSE_FNO")
    assert any("freeze limit" in v for v in vs)


def test_check_lot_freeze_missing_freeze_uses_settings_fallback():
    fz_map = {"NIFTY": 1800}
    vs = _check_lot_freeze(2000, 1, None, fz_map, "NIFTY13", "NSE_FNO")
    assert any("freeze limit" in v for v in vs)


def test_check_lot_freeze_missing_freeze_no_fallback_match_skips():
    vs = _check_lot_freeze(9999, 1, None, {}, "13", "NSE_FNO")
    assert vs == []


def test_check_lot_freeze_lot_size_one_skips_lot_check():
    # lot_size=1 means no lot constraint — any qty is valid
    assert _check_lot_freeze(7, 1, None, {}, "13", "NSE_FNO") == []


# ── MarginService routing (S2 — single vs basket endpoint) ───────────────────

def _make_service() -> MarginService:
    svc = MarginService.__new__(MarginService)
    svc._client_id = "client123"
    svc._access_token = "token456"
    svc._client = None
    return svc


def _spec(security_id: str = "13") -> OrderSpec:
    return OrderSpec(
        security_id=security_id,
        exchange_segment="NSE_FNO",
        transaction_type="SELL",
        quantity=50,
        price=Decimal("100"),
        product="NRML",
    )


async def _sync_to_thread(fn, *args, **kwargs):
    """Stand-in for asyncio.to_thread that calls fn synchronously (test-only)."""
    return fn(*args, **kwargs)


@pytest.mark.asyncio
async def test_single_leg_calls_margin_calculator():
    svc = _make_service()
    mock_client = MagicMock()
    mock_client.margin_calculator.return_value = {"totalMargin": "12500.0"}
    svc._client = mock_client

    with patch("pdp.orders.margin.asyncio.to_thread", side_effect=_sync_to_thread):
        result = await svc.required_margin([_spec()])

    mock_client.margin_calculator.assert_called_once()
    mock_client.margin_calculator_basket.assert_not_called()
    assert result == Decimal("12500.0")


@pytest.mark.asyncio
async def test_multi_leg_calls_basket_margin_calculator():
    svc = _make_service()
    mock_client = MagicMock()
    mock_client.margin_calculator_basket.return_value = {"totalMargin": "27000.0"}
    svc._client = mock_client

    with patch("pdp.orders.margin.asyncio.to_thread", side_effect=_sync_to_thread):
        result = await svc.required_margin([_spec("13"), _spec("25")])

    mock_client.margin_calculator_basket.assert_called_once()
    mock_client.margin_calculator.assert_not_called()
    assert result == Decimal("27000.0")


@pytest.mark.asyncio
async def test_empty_orders_returns_zero():
    svc = _make_service()
    result = await svc.required_margin([])
    assert result == Decimal("0")
