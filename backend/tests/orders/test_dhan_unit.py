"""Unit tests for the Dhan field-mapping helper ``_to_dhan_params``."""
from __future__ import annotations

from decimal import Decimal

import pytest

from pdp.orders.dhan_broker import _remarks_str, _to_dhan_params
from pdp.orders.models import Order, OrderStatus, OrderType, Product, Side


def _order(
    order_type: str = OrderType.MARKET,
    product: str = Product.NRML,
    segment: str = "NSE_FNO",
    side: str = Side.BUY,
    price=None,
    trigger=None,
    client_order_id: str | None = "cid-1",
) -> Order:
    return Order(
        id=1,
        client_order_id=client_order_id,
        broker="dhan",
        mode="LIVE",
        security_id="13",
        exchange_segment=segment,
        side=side,
        qty=50,
        order_type=order_type,
        price=price,
        trigger_price=trigger,
        product=product,
        status=OrderStatus.OPEN,
    )


@pytest.mark.parametrize(
    ("our_type", "dhan_type"),
    [
        (OrderType.MARKET, "MARKET"),
        (OrderType.LIMIT, "LIMIT"),
        (OrderType.SL, "STOP_LOSS"),
        (OrderType.SL_M, "STOP_LOSS_MARKET"),
    ],
)
def test_order_type_mapping(our_type: str, dhan_type: str) -> None:
    params = _to_dhan_params(_order(order_type=our_type))
    assert params["order_type"] == dhan_type


@pytest.mark.parametrize(
    ("our_product", "dhan_product"),
    [
        (Product.NRML, "MARGIN"),
        (Product.MIS, "INTRADAY"),
        (Product.INTRADAY, "INTRADAY"),
        (Product.DELIVERY, "CNC"),
    ],
)
def test_product_mapping(our_product: str, dhan_product: str) -> None:
    params = _to_dhan_params(_order(product=our_product))
    assert params["product_type"] == dhan_product


@pytest.mark.parametrize(
    ("our_segment", "dhan_segment"),
    [
        ("NSE_CUR", "NSE_CURRENCY"),
        ("BSE_CUR", "BSE_CURRENCY"),
        ("NSE_FNO", "NSE_FNO"),  # passthrough
        ("NSE_EQ", "NSE_EQ"),  # passthrough
        ("BSE_FNO", "BSE_FNO"),  # passthrough
    ],
)
def test_segment_mapping(our_segment: str, dhan_segment: str) -> None:
    params = _to_dhan_params(_order(segment=our_segment))
    assert params["exchange_segment"] == dhan_segment


def test_transaction_type_is_direct() -> None:
    assert _to_dhan_params(_order(side=Side.BUY))["transaction_type"] == "BUY"
    assert _to_dhan_params(_order(side=Side.SELL))["transaction_type"] == "SELL"


def test_client_order_id_sent_as_tag() -> None:
    assert _to_dhan_params(_order(client_order_id="abc-123"))["tag"] == "abc-123"
    assert _to_dhan_params(_order(client_order_id=None))["tag"] is None


def test_prices_coerced_to_float() -> None:
    params = _to_dhan_params(
        _order(order_type=OrderType.SL, price=Decimal("100.5"), trigger=Decimal("99.25"))
    )
    assert params["price"] == 100.5
    assert params["trigger_price"] == 99.25
    assert isinstance(params["price"], float)


def test_missing_prices_default_to_zero() -> None:
    params = _to_dhan_params(_order(order_type=OrderType.MARKET))
    assert params["price"] == 0.0
    assert params["trigger_price"] == 0.0


def test_quantity_passthrough() -> None:
    assert _to_dhan_params(_order())["quantity"] == 50


def test_remarks_str_extracts_error_message() -> None:
    assert _remarks_str({"error_message": "insufficient funds"}) == "insufficient funds"
    assert _remarks_str("plain string") == "plain string"
    assert _remarks_str(None) == "rejected by broker"
