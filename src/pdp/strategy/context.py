from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select

from pdp.orders.models import Order, OrderStatus, OrderType, Product, Side

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.indicators.engine import IndicatorEngine
    from pdp.indicators.supertrend import SuperTrendState
    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.orders.router import OrderRouter
    from pdp.strategy.registry import WatchlistEntry


class RiskCapBreached(Exception):
    """Raised when a strategy's risk cap would be exceeded by a new order."""


class IndicatorReader:
    """Read-only view over the universal indicator engine for strategies."""

    def __init__(self, engine: IndicatorEngine | None) -> None:
        self._engine = engine

    def supertrend(self, security_id: str, timeframe: str) -> SuperTrendState | None:
        if self._engine is None:
            return None
        return self._engine.get(security_id, timeframe)


class MarketControl:
    """Lets a strategy subscribe/unsubscribe feed instruments at runtime.

    No-op when no live Dhan adapter is configured (e.g. paper smoke tests).
    """

    def __init__(
        self,
        adapter: DhanTickerAdapter | None,
        session_maker: async_sessionmaker[AsyncSession] | None,
    ) -> None:
        self._adapter = adapter
        self._session_maker = session_maker

    async def subscribe(self, security_id: str, segment: str) -> bool:
        if self._adapter is None or self._session_maker is None:
            return False
        async with self._session_maker() as session:
            return await self._adapter.subscribe(security_id, segment, session)

    async def unsubscribe(self, security_id: str, segment: str) -> None:
        if self._adapter is None or self._session_maker is None:
            return
        async with self._session_maker() as session:
            await self._adapter.unsubscribe(security_id, segment, session)


@dataclass
class StrategyContext:
    orders: StrategyOrderClient
    params: dict[str, Any]
    watchlist: list[WatchlistEntry]
    log: Any = field(default_factory=structlog.get_logger)
    indicators: IndicatorReader | None = None
    market: MarketControl | None = None
    session_maker: async_sessionmaker[AsyncSession] | None = None


class StrategyOrderClient:
    """Wraps OrderRouter for strategy use: manages sessions, enforces risk caps."""

    def __init__(
        self,
        strategy_id: str,
        order_router: OrderRouter,
        session_maker: async_sessionmaker[AsyncSession],
        max_open_orders: int,
        max_daily_loss_inr: float,
    ) -> None:
        self._strategy_id = strategy_id
        self._router = order_router
        self._session_maker = session_maker
        self._max_open_orders = max_open_orders
        self._max_daily_loss_inr = Decimal(str(max_daily_loss_inr))

    async def place_order(
        self,
        *,
        security_id: str,
        exchange_segment: str,
        side: str | Side,
        qty: int,
        order_type: str | OrderType = OrderType.MARKET,
        product: str | Product = Product.MIS,
        price: Decimal | None = None,
        trigger_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        async with self._session_maker() as session:
            await self._check_risk(session)
            return await self._router.place_order(
                session,
                client_order_id=client_order_id,
                security_id=security_id,
                exchange_segment=exchange_segment,
                side=str(side),
                qty=qty,
                order_type=str(order_type),
                price=price,
                trigger_price=trigger_price,
                product=str(product),
                strategy_id=self._strategy_id,
            )

    async def cancel_order(self, order_id: int) -> Order | None:
        async with self._session_maker() as session:
            return await self._router.cancel_order(session, order_id)

    async def _check_risk(self, session: AsyncSession) -> None:
        open_count = await self._count_open_orders(session)
        if open_count >= self._max_open_orders:
            raise RiskCapBreached(
                f"strategy {self._strategy_id!r} already has {open_count} open "
                f"orders (cap: {self._max_open_orders})"
            )

    async def _count_open_orders(self, session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count()).select_from(Order).where(
                Order.strategy_id == self._strategy_id,
                Order.status == OrderStatus.OPEN,
            )
        )
        return result.scalar_one()
