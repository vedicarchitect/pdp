from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.instruments.models import Instrument
from pdp.orders.models import Order, OrderStatus, TradeMode

if TYPE_CHECKING:
    from pdp.orders.dhan_broker import DhanBroker
    from pdp.orders.paper import PaperBroker
    from pdp.settings import Settings

log = structlog.get_logger()


def select_broker(settings: Settings) -> tuple[str, str]:
    """Return (broker_name, mode) based on settings.  v1 always returns paper."""
    if settings.LIVE and settings.BROKER == "dhan" and settings.DHAN_CLIENT_ID:
        return ("dhan", TradeMode.LIVE)
    return ("paper", TradeMode.PAPER)


class OrderRouter:
    """
    Validates, persists, and routes order placement requests.

    Handles:
    - Idempotency via client_order_id UNIQUE constraint
    - Lot-size validation against instruments table
    - Broker selection (paper in v1)
    - Handing filled orders to PaperBroker
    """

    def __init__(
        self,
        settings: Settings,
        paper: PaperBroker,
        dhan_broker: DhanBroker | None = None,
    ) -> None:
        self._settings = settings
        self._paper = paper
        self._dhan = dhan_broker

    def _broker_for(self, broker: str) -> PaperBroker | DhanBroker:
        """Select the engine that owns orders for the given broker name."""
        if broker == "dhan" and self._dhan is not None:
            return self._dhan
        return self._paper

    async def place_order(
        self,
        session: AsyncSession,
        *,
        client_order_id: str | None,
        security_id: str,
        exchange_segment: str,
        side: str,
        qty: int,
        order_type: str,
        price: Decimal | None,
        trigger_price: Decimal | None,
        product: str,
        strategy_id: str | None,
    ) -> Order:
        broker, mode = select_broker(self._settings)

        # Lot-size check
        reject_reason = await self._validate_lot_size(session, security_id, exchange_segment, qty)

        # Idempotency: return existing order if client_order_id already exists
        if client_order_id:
            existing = await self._find_by_client_id(session, client_order_id)
            if existing is not None:
                return existing

        status = OrderStatus.REJECTED if reject_reason else OrderStatus.OPEN

        order = Order(
            client_order_id=client_order_id,
            broker=broker,
            mode=mode,
            security_id=security_id,
            exchange_segment=exchange_segment,
            side=side,
            qty=qty,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            product=product,
            status=status,
            placed_at=datetime.now(UTC),
            reject_reason=reject_reason,
            strategy_id=strategy_id,
        )
        session.add(order)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            existing = await self._find_by_client_id(session, client_order_id)
            if existing is not None:
                return existing
            raise

        await session.commit()
        await session.refresh(order)

        if status == OrderStatus.OPEN:
            await self._broker_for(broker).add_order(order)
            log.info(
                "order_placed",
                order_id=order.id,
                broker=broker,
                security_id=security_id,
                order_type=order_type,
            )
        else:
            log.info("order_rejected", order_id=order.id, reason=reject_reason)

        return order

    async def cancel_order(self, session: AsyncSession, order_id: int) -> Order | None:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order is None:
            return None
        if order.status not in (OrderStatus.NEW, OrderStatus.OPEN):
            return order  # already terminal — return as-is
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(UTC)
        await session.commit()
        await self._broker_for(order.broker).cancel_order(order_id)
        return order

    async def _validate_lot_size(
        self,
        session: AsyncSession,
        security_id: str,
        exchange_segment: str,
        qty: int,
    ) -> str | None:
        result = await session.execute(
            select(Instrument.lot_size).where(
                Instrument.security_id == security_id,
                Instrument.exchange_segment == exchange_segment,
            )
        )
        row = result.first()
        if row is None:
            return None  # unknown instrument — allow, broker handles it
        lot_size: int = row[0]
        if lot_size > 1 and qty % lot_size != 0:
            return f"qty not multiple of lot_size ({lot_size})"
        return None

    async def _find_by_client_id(self, session: AsyncSession, client_order_id: str) -> Order | None:
        result = await session.execute(
            select(Order).where(Order.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()
