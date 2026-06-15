"""Unit tests for the kill-switch service."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.orders.models import Order, OrderStatus, Position, Product, Side
from pdp.risk.service import KillSwitchService


def _mock_order(order_id: int, security_id: str = "13", strategy_id: str | None = None) -> Order:
    o = MagicMock(spec=Order)
    o.id = order_id
    o.security_id = security_id
    o.strategy_id = strategy_id
    o.status = OrderStatus.OPEN
    return o


def _mock_position(
    security_id: str = "13",
    exchange_segment: str = "NSE_FNO",
    product: str = Product.MIS,
    net_qty: int = 50,
) -> Position:
    p = MagicMock(spec=Position)
    p.security_id = security_id
    p.exchange_segment = exchange_segment
    p.product = product
    p.net_qty = net_qty
    return p


def _build_session_maker(open_orders=None, positions=None):
    """Return a session_maker that yields a mock session."""
    open_orders = open_orders or []
    positions = positions or []

    # Build mock scalars result for orders query (returns (id, security_id, strategy_id) rows)
    order_rows = [
        MagicMock(id=o.id, security_id=o.security_id, strategy_id=o.strategy_id)
        for o in open_orders
    ]
    pos_objects = positions

    call_count = [0]

    @asynccontextmanager
    async def session_maker():
        session = AsyncMock()

        async def execute(stmt):
            result = MagicMock()
            # Alternate between orders query and positions query
            if call_count[0] == 0:
                result.all.return_value = order_rows
            else:
                result.scalars.return_value.all.return_value = pos_objects
            call_count[0] += 1
            return result

        session.execute = execute
        yield session

    return session_maker


@pytest.mark.asyncio
async def test_kill_switch_cancels_open_orders_and_flattens_positions():
    ks = KillSwitchService()

    open_orders = [_mock_order(1, "13", "strat-1"), _mock_order(2, "42", None)]
    positions = [_mock_position("13", "NSE_FNO", Product.MIS.value, 50)]

    cancelled_order = MagicMock()
    cancelled_order.id = 1
    cancelled_order.security_id = "13"
    cancelled_order.strategy_id = "strat-1"

    order_router = MagicMock()
    order_router.cancel_order = AsyncMock(return_value=cancelled_order)
    order_router.place_order = AsyncMock(return_value=MagicMock())

    session_maker = _build_session_maker(open_orders, positions)
    result = await ks.execute(session_maker, order_router, {"ip": "127.0.0.1"})

    assert result["status"] in ("ok", "partial")
    assert order_router.cancel_order.await_count == len(open_orders)
    assert order_router.place_order.await_count == len(positions)

    # Flattened position should be a SELL (net_qty > 0)
    call_kwargs = order_router.place_order.await_args_list[0][1]
    assert call_kwargs["side"] == str(Side.SELL)
    assert call_kwargs["qty"] == 50
    assert call_kwargs["order_type"] == "MARKET"


@pytest.mark.asyncio
async def test_kill_switch_empty_orders_and_positions():
    ks = KillSwitchService()
    order_router = MagicMock()
    order_router.cancel_order = AsyncMock()
    order_router.place_order = AsyncMock()

    session_maker = _build_session_maker([], [])
    result = await ks.execute(session_maker, order_router, {"ip": "127.0.0.1"})

    assert result["status"] == "ok"
    assert result["cancelled_orders"] == []
    assert result["flattened_positions"] == []
    assert result["errors"] == []
    order_router.cancel_order.assert_not_awaited()
    order_router.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_partial_failure_on_cancel():
    ks = KillSwitchService()

    open_orders = [_mock_order(1), _mock_order(2)]
    positions = []

    order_router = MagicMock()
    order_router.cancel_order = AsyncMock(side_effect=[Exception("broker timeout"), MagicMock(id=2, security_id="42", strategy_id=None)])
    order_router.place_order = AsyncMock()

    session_maker = _build_session_maker(open_orders, positions)
    result = await ks.execute(session_maker, order_router, {"ip": "127.0.0.1"})

    assert result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert "cancel_order 1" in result["errors"][0]


@pytest.mark.asyncio
async def test_kill_switch_flattens_short_position_with_buy():
    ks = KillSwitchService()

    positions = [_mock_position("13", "NSE_FNO", Product.INTRADAY.value, -100)]
    open_orders = []

    order_router = MagicMock()
    order_router.cancel_order = AsyncMock()
    order_router.place_order = AsyncMock(return_value=MagicMock())

    session_maker = _build_session_maker(open_orders, positions)
    result = await ks.execute(session_maker, order_router, {"ip": "127.0.0.1"})

    call_kwargs = order_router.place_order.await_args_list[0][1]
    assert call_kwargs["side"] == str(Side.BUY)
    assert call_kwargs["qty"] == 100


@pytest.mark.asyncio
async def test_kill_switch_skips_delivery_positions():
    """DELIVERY and NRML products must NOT be flattened by kill-switch."""
    ks = KillSwitchService()

    # Only DELIVERY positions — none should be flattened
    positions = [_mock_position("13", "NSE_EQ", Product.DELIVERY.value, 10)]
    open_orders = []

    order_router = MagicMock()
    order_router.cancel_order = AsyncMock()
    order_router.place_order = AsyncMock()

    session_maker = _build_session_maker(open_orders, positions)
    # The session_maker won't return DELIVERY positions because they're filtered
    # by product.in_(INTRADAY_PRODUCTS) in the query. We mock an empty result.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def empty_session_maker():
        session = AsyncMock()

        async def execute(stmt):
            result = MagicMock()
            result.all.return_value = []         # no open orders
            result.scalars.return_value.all.return_value = []  # no intraday positions
            return result

        session.execute = execute
        yield session

    result = await ks.execute(empty_session_maker, order_router, {"ip": "127.0.0.1"})
    order_router.place_order.assert_not_awaited()
    assert result["flattened_positions"] == []
