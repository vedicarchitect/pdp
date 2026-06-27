"""
Integration tests for the Dhan broker, exercising add_order, the order-update
fill path, rejection, and reconciliation idempotency without a real database or
the live SDK — sessions and the dhanhq client are mocked.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.orders.dhan_broker import DhanBroker
from pdp.orders.models import (
    BrokerCost,
    Order,
    OrderStatus,
    OrderType,
    Product,
    Side,
    Trade,
)
from pdp.orders.paper import ChargesCalculator


class _FakeSessionMaker:
    """Returns the same mock session as an async context manager each call."""

    def __init__(self, session: MagicMock) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionMaker:
        return self

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _broker(session: MagicMock) -> DhanBroker:
    """Build a DhanBroker bypassing __init__/network, wired to a mock session."""
    broker = DhanBroker.__new__(DhanBroker)
    broker._session_maker = _FakeSessionMaker(session)
    broker._client = MagicMock()
    broker._loop = None
    broker._hub = None
    broker._costs = {}
    broker._order_update = None
    broker._ou_task = None

    async def _direct_call(fn, *args, **kwargs):  # bypass executor in tests
        return fn(*args, **kwargs)

    broker._call = _direct_call  # type: ignore[assignment]
    return broker


def _order(
    order_id: int = 1,
    status: str = OrderStatus.OPEN,
    broker_order_id: str | None = None,
) -> Order:
    return Order(
        id=order_id,
        client_order_id=f"cid-{order_id}",
        broker_order_id=broker_order_id,
        broker="dhan",
        mode="LIVE",
        security_id="13",
        exchange_segment="NSE_FNO",
        side=Side.BUY,
        qty=50,
        order_type=OrderType.MARKET,
        price=None,
        trigger_price=None,
        product=Product.NRML,
        status=status,
    )


def _cost() -> BrokerCost:
    return BrokerCost(
        broker="dhan",
        instrument_type="FUTIDX",
        brokerage_bps=Decimal("0"),
        brokerage_flat=Decimal("20"),
        stt_bps=Decimal("1"),
        exchange_fee_bps=Decimal("0.05"),
        gst_pct=Decimal("18"),
        sebi_charges_bps=Decimal("0.0001"),
        stamp_duty_bps=Decimal("0.002"),
    )


# ------------------------------------------------------------------ #
# add_order                                                           #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_add_order_places_and_stores_broker_order_id() -> None:
    executed: list = []

    async def rec_execute(stmt, *a, **k):
        executed.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = rec_execute
    session.commit = AsyncMock()

    broker = _broker(session)
    broker._client.place_order = MagicMock(
        return_value={"status": "success", "data": {"orderId": "DH123"}}
    )

    order = _order()
    await broker.add_order(order)

    # place_order called with mapped params + client_order_id as tag
    _, kwargs = broker._client.place_order.call_args
    assert kwargs["order_type"] == "MARKET"
    assert kwargs["product_type"] == "MARGIN"
    assert kwargs["transaction_type"] == "BUY"
    assert kwargs["tag"] == "cid-1"

    # broker_order_id persisted via an UPDATE
    params = executed[-1].compile().params
    assert params["broker_order_id"] == "DH123"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_add_order_failure_marks_rejected() -> None:
    executed: list = []

    async def rec_execute(stmt, *a, **k):
        executed.append(stmt)
        return MagicMock()

    session = MagicMock()
    session.execute = rec_execute
    session.commit = AsyncMock()

    broker = _broker(session)
    broker._client.place_order = MagicMock(
        return_value={"status": "failure", "remarks": {"error_message": "insufficient funds"}}
    )

    order = _order()
    await broker.add_order(order)

    params = executed[-1].compile().params
    assert params["status"] == OrderStatus.REJECTED
    assert "insufficient" in params["reject_reason"]


# ------------------------------------------------------------------ #
# Order-update fill path                                              #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_traded_alert_creates_trade_and_position() -> None:
    order = _order(broker_order_id="DH123")

    order_result = MagicMock(scalar_one_or_none=MagicMock(return_value=order))
    update_result = MagicMock()
    position_result = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[order_result, update_result, position_result])
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    broker = _broker(session)
    broker._costs = {"FUTIDX": ChargesCalculator(_cost())}
    broker._hub = MagicMock()
    broker._client.get_trade_book = MagicMock(
        return_value={"status": "success", "data": [{"tradedQuantity": 50, "tradedPrice": 200.5}]}
    )

    await broker._handle_alert("DH123", "TRADED")

    # A Trade and a Position were added
    added_types = {type(c.args[0]).__name__ for c in session.add.call_args_list}
    assert "Trade" in added_types
    assert "Position" in added_types

    # Trade captured the broker fill price
    trade = next(c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], Trade))
    assert trade.fill_price == Decimal("200.5000")
    assert trade.charges > Decimal("0")

    # Order transitioned + events published
    assert order.status == OrderStatus.FILLED
    published = {c.args[0] for c in broker._hub.publish.call_args_list}
    assert {"order", "trade", "position"} <= published


@pytest.mark.asyncio
async def test_traded_alert_idempotent_when_already_filled() -> None:
    """A second TRADED for an already-FILLED order must not create a new trade."""
    order = _order(status=OrderStatus.FILLED, broker_order_id="DH123")

    order_result = MagicMock(scalar_one_or_none=MagicMock(return_value=order))
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[order_result])
    session.add = MagicMock()
    session.commit = AsyncMock()

    broker = _broker(session)
    broker._client.get_trade_book = MagicMock(
        return_value={"status": "success", "data": [{"tradedQuantity": 50, "tradedPrice": 200.5}]}
    )

    await broker._handle_alert("DH123", "TRADED")

    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_alert_transitions_order() -> None:
    order = _order(broker_order_id="DH123")
    order_result = MagicMock(scalar_one_or_none=MagicMock(return_value=order))
    executed: list = []

    async def rec_execute(stmt, *a, **k):
        executed.append(stmt)
        return order_result

    session = MagicMock()
    session.execute = rec_execute
    session.commit = AsyncMock()

    broker = _broker(session)
    await broker._handle_alert("DH123", "REJECTED")

    assert order.status == OrderStatus.REJECTED
    params = executed[-1].compile().params
    assert params["status"] == OrderStatus.REJECTED
