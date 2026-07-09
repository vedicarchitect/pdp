from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select

from pdp.orders.models import Order, OrderStatus, OrderType, Position, Product, Side

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.indicators.engine import IndicatorEngine
    from pdp.indicators.supertrend import SuperTrendState
    from pdp.market.dhan_ws import DhanTickerAdapter
    from pdp.orders.paper import PaperBroker
    from pdp.orders.router import OrderRouter
    from pdp.strategy.registry import WatchlistEntry


class RiskCapBreached(Exception):  # noqa: N818
    """Raised when a strategy's risk cap would be exceeded by a new order."""


class IndicatorReader:
    """Read-only view over the universal indicator engine for strategies."""

    def __init__(self, engine: IndicatorEngine | None) -> None:
        self._engine = engine

    def supertrend(self, security_id: str, timeframe: str) -> SuperTrendState | None:
        if self._engine is None:
            return None
        return self._engine.get(security_id, timeframe)

    def snapshot(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_snapshot(security_id, timeframe)

    def ema(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_ema(security_id, timeframe)

    def rsi(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_rsi(security_id, timeframe)

    def psar(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_psar(security_id, timeframe)

    def vwap(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_vwap(security_id, timeframe)

    def vwma(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_vwma(security_id, timeframe)

    def pivots(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_pivots(security_id, timeframe)

    def period_levels(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_period_levels(security_id, timeframe)

    def fvg(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_fvg(security_id, timeframe)

    def market_profile(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_market_profile(security_id, timeframe)

    def volume_profile(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_volume_profile(security_id, timeframe)

    def macd(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_macd(security_id, timeframe)

    def candlestick(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_candlestick(security_id, timeframe)

    def elliott(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_elliott(security_id, timeframe)

    def fib_levels(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_fib_levels(security_id, timeframe)

    def elder_impulse(self, security_id: str, timeframe: str) -> Any:
        if self._engine is None:
            return None
        return self._engine.get_elder_impulse(security_id, timeframe)

    def ml_signal(self, security_id: str, timeframe: str) -> Any:
        """Read-only ML directional signal. Returns None when no model is loaded."""
        if self._engine is None:
            return None
        return self._engine.get_ml_signal(security_id, timeframe)


class MarketControl:
    """Lets a strategy subscribe/unsubscribe feed instruments at runtime.

    No-op when no live Dhan adapter is configured (e.g. paper smoke tests).
    """

    def __init__(
        self,
        adapter: DhanTickerAdapter | None,
        session_maker: async_sessionmaker[AsyncSession] | None,
        redis: Redis | None = None,
        paper_broker: PaperBroker | None = None,
        on_subscribe: Callable[[str], None] | None = None,
        on_unsubscribe: Callable[[str], None] | None = None,
    ) -> None:
        self._adapter = adapter
        self._session_maker = session_maker
        self._redis = redis
        self._paper_broker = paper_broker
        self._on_subscribe = on_subscribe
        self._on_unsubscribe = on_unsubscribe

    async def subscribe(self, security_id: str, segment: str) -> bool:
        # Pre-register with paper broker before the Dhan subscription so the first
        # tick after place_order() fills the MARKET order without being missed.
        if self._paper_broker is not None:
            self._paper_broker.notify_subscribe(security_id)
        # Notify the host so this SID's ticks are routed to strategy.on_tick().
        if self._on_subscribe is not None:
            self._on_subscribe(security_id)
        if self._adapter is None or self._session_maker is None:
            return False
        async with self._session_maker() as session:
            return await self._adapter.subscribe(security_id, segment, session)

    async def unsubscribe(self, security_id: str, segment: str) -> None:
        if self._on_unsubscribe is not None:
            self._on_unsubscribe(security_id)
        if self._adapter is None or self._session_maker is None:
            return
        async with self._session_maker() as session:
            await self._adapter.unsubscribe(security_id, segment, session)

    async def cache_get(self, key: str) -> str | None:
        """Read an arbitrary string value from the Redis hot cache."""
        if self._redis is None:
            return None
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    async def cache_set(self, key: str, value: str, ex: int | None = None) -> None:
        """Write an arbitrary string value to the Redis hot cache."""
        if self._redis is not None:
            await self._redis.set(key, value, ex=ex)

    async def ltp(self, security_id: str) -> Decimal | None:
        """Latest traded price from the Redis hot cache, or None if unavailable.

        Returns None for a missing key or a non-positive price so callers (e.g. a
        stop check) never act on a stale/zero quote.
        """
        if self._redis is None:
            return None
        raw = await self._redis.get(f"ltp:{security_id}")
        if raw is None:
            return None
        try:
            val = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
        return val if val > 0 else None

    async def ltp_with_age(self, security_id: str) -> tuple[Decimal | None, float | None]:
        """Return (ltp, age_seconds) from Redis. age_seconds is None when timestamp absent.

        Uses ltp_ts:{sid} written by the tick router on every tick. Callers use the age
        to decide whether the price is fresh enough to act on (e.g. for leg-stop checks).
        """
        import time as _time

        if self._redis is None:
            return None, None
        raw_ltp, raw_ts = await self._redis.mget(f"ltp:{security_id}", f"ltp_ts:{security_id}")
        if raw_ltp is None:
            return None, None
        try:
            val = Decimal(str(raw_ltp))
        except (InvalidOperation, ValueError):
            return None, None
        if val <= 0:
            return None, None
        age: float | None = None
        if raw_ts is not None:
            try:
                age = _time.time() - float(raw_ts)
            except (ValueError, TypeError):
                pass
        return val, age


@dataclass
class StrategyContext:
    orders: StrategyOrderClient
    params: dict[str, Any]
    watchlist: list[WatchlistEntry]
    log: Any = field(default_factory=structlog.get_logger)
    indicators: IndicatorReader | None = None
    market: MarketControl | None = None
    session_maker: async_sessionmaker[AsyncSession] | None = None
    chain_hub: Any | None = None
    _event_service: Any | None = None

    def emit_critical(
        self,
        event_type: Any,
        security_id: str,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._event_service is not None:
            self._event_service.emit_critical(event_type, security_id, title, message, payload)


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

    async def cancel_open_entry_orders(self, security_id: str) -> list[int]:
        """Cancel all OPEN SELL orders this strategy has on a security."""
        async with self._session_maker() as session:
            return await self._router.cancel_open_entry_orders(session, security_id, self._strategy_id)

    async def get_net_qty(self, security_id: str) -> int:
        """Return net_qty from the positions table for this strategy+security (0 if no row)."""
        async with self._session_maker() as session:
            result = await session.execute(
                select(Position.net_qty).where(
                    Position.strategy_id == self._strategy_id,
                    Position.security_id == security_id,
                )
            )
            row = result.first()
            return int(row[0]) if row else 0

    async def get_position(self, security_id: str) -> tuple[int, Decimal]:
        """Return ``(net_qty, avg_price)`` from the positions table (``(0, 0)`` if no row).

        ``avg_price`` is the weighted-average fill price (a positive number even for a
        short, per the ledger's convention), suitable for mark-to-market.
        """
        async with self._session_maker() as session:
            result = await session.execute(
                select(Position.net_qty, Position.avg_price).where(
                    Position.strategy_id == self._strategy_id,
                    Position.security_id == security_id,
                )
            )
            row = result.first()
            if row is None:
                return 0, Decimal("0")
            return int(row[0]), Decimal(str(row[1]))

    async def get_realized_pnl(self, security_id: str) -> Decimal:
        """Return cumulative realized P&L from the positions table (0 if no row)."""
        async with self._session_maker() as session:
            result = await session.execute(
                select(Position.realized_pnl).where(
                    Position.strategy_id == self._strategy_id,
                    Position.security_id == security_id,
                )
            )
            row = result.first()
            return Decimal(str(row[0])) if row else Decimal("0")

    async def get_realized_pnl_per_security(self) -> dict[str, Decimal]:
        """Realized P&L from positions for this strategy keyed by security_id."""
        async with self._session_maker() as session:
            result = await session.execute(
                select(Position.security_id, Position.realized_pnl).where(
                    Position.strategy_id == self._strategy_id,
                )
            )
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def get_positions(self) -> list[Position]:
        """Positions with net_qty != 0 belonging to this strategy."""
        async with self._session_maker() as session:
            result = await session.execute(
                select(Position).where(
                    Position.strategy_id == self._strategy_id,
                    Position.net_qty != 0,
                )
            )
            return list(result.scalars().all())

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    async def _check_risk(self, session: AsyncSession) -> None:
        open_count = await self._count_open_orders(session)
        if open_count >= self._max_open_orders:
            raise RiskCapBreached(
                f"strategy {self._strategy_id!r} already has {open_count} open "
                f"orders (cap: {self._max_open_orders})"
            )

    async def _count_open_orders(self, session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.strategy_id == self._strategy_id,
                Order.status == OrderStatus.OPEN,
            )
        )
        return result.scalar_one()
