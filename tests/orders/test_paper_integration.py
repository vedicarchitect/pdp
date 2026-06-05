"""
Integration tests for the paper broker fill pipeline.

These tests do NOT require a running database — they exercise the pure logic
of PaperBroker._fill, position upsert, and charges by injecting mock sessions
and stubs.  DB integration tests (with a real Postgres) are deferred to CI.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.orders.models import (
    BrokerCost,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Side,
)
from pdp.orders.paper import PaperBroker, _should_fill


def _open_order(
    order_id: int = 1,
    security_id: str = "13",
    side: str = Side.BUY,
    qty: int = 50,
    order_type: str = OrderType.MARKET,
    price=None,
    trigger=None,
) -> Order:
    return Order(
        id=order_id,
        client_order_id=f"cid-{order_id}",
        broker="paper",
        mode="PAPER",
        security_id=security_id,
        exchange_segment="NSE_FNO",
        side=side,
        qty=qty,
        order_type=order_type,
        price=price,
        trigger_price=trigger,
        product=Product.NRML,
        status=OrderStatus.OPEN,
    )


def _cost_row() -> BrokerCost:
    return BrokerCost(
        broker="paper",
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
# Fill logic tests (pure, no DB)                                      #
# ------------------------------------------------------------------ #

class TestFillLogic:
    def test_market_order_fills_on_any_tick(self) -> None:
        o = _open_order(order_type=OrderType.MARKET)
        assert _should_fill(o, Decimal("24500"))

    def test_limit_buy_does_not_fill_above_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, price=Decimal("24400"))
        assert not _should_fill(o, Decimal("24500"))
        assert not _should_fill(o, Decimal("24450"))

    def test_limit_buy_fills_at_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, price=Decimal("24400"))
        assert _should_fill(o, Decimal("24400"))
        assert _should_fill(o, Decimal("24380"))

    def test_limit_sell_does_not_fill_below_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, side=Side.SELL, price=Decimal("24600"))
        assert not _should_fill(o, Decimal("24500"))

    def test_limit_sell_fills_at_or_above_limit(self) -> None:
        o = _open_order(order_type=OrderType.LIMIT, side=Side.SELL, price=Decimal("24600"))
        assert _should_fill(o, Decimal("24600"))
        assert _should_fill(o, Decimal("24700"))


# ------------------------------------------------------------------ #
# Position math tests                                                 #
# ------------------------------------------------------------------ #

class TestPositionMathDirect:
    """Test position upsert logic without DB by calling internals directly."""

    @pytest.mark.asyncio
    async def test_add_to_existing_long_position(self) -> None:
        """BUY 50 @ 100 then BUY 50 @ 110 → avg_price = 105."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        # Existing position
        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=50,
            avg_price=Decimal("100"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.BUY, qty=50)
        await broker._upsert_position(session, order, Decimal("110"), datetime.now(UTC))

        assert pos.net_qty == 100
        assert pos.avg_price == Decimal("105.0000")

    @pytest.mark.asyncio
    async def test_realize_on_reduce(self) -> None:
        """BUY 50 @ 105 avg, SELL 50 @ 120 → realized_pnl = 750, net = 0."""
        broker = PaperBroker.__new__(PaperBroker)
        broker._slippage_bps = Decimal("0")
        broker._costs = {}
        broker._hub = None

        pos = Position(
            id=1,
            security_id="13",
            exchange_segment="NSE_FNO",
            product=Product.NRML,
            net_qty=50,
            avg_price=Decimal("105"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: pos))
        session.flush = AsyncMock()

        order = _open_order(side=Side.SELL, qty=50)
        await broker._upsert_position(session, order, Decimal("120"), datetime.now(UTC))

        assert pos.net_qty == 0
        assert pos.realized_pnl == Decimal("750.0000")


# ------------------------------------------------------------------ #
# Charges                                                             #
# ------------------------------------------------------------------ #

class TestChargesIntegration:
    def test_optidx_charges_positive(self) -> None:
        from pdp.orders.paper import ChargesCalculator

        cost = BrokerCost(
            broker="paper",
            instrument_type="OPTIDX",
            brokerage_bps=Decimal("0"),
            brokerage_flat=Decimal("20"),
            stt_bps=Decimal("0.05"),
            exchange_fee_bps=Decimal("0.53"),
            gst_pct=Decimal("18"),
            sebi_charges_bps=Decimal("0.0001"),
            stamp_duty_bps=Decimal("0.003"),
        )
        calc = ChargesCalculator(cost)
        charges = calc.compute(qty=50, fill_price=Decimal("200"), side=Side.SELL)
        assert charges > Decimal("0"), f"charges should be positive, got {charges}"
