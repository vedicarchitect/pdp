from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select, update

from pdp.orders.models import (
    BrokerCost,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Side,
    Trade,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.orders.ws import OrdersHub

log = structlog.get_logger()

_FOUR = Decimal("0.0001")


def _round4(v: Decimal) -> Decimal:
    return v.quantize(_FOUR, rounding=ROUND_HALF_UP)


class ChargesCalculator:
    """Computes transaction charges from broker_costs table."""

    def __init__(self, costs: BrokerCost) -> None:
        self._c = costs

    def compute(self, qty: int, fill_price: Decimal, side: str) -> Decimal:
        c = self._c
        trade_value = Decimal(str(qty)) * fill_price

        brokerage = min(
            trade_value * c.brokerage_bps / Decimal("10000"),
            c.brokerage_flat if c.brokerage_flat > 0 else Decimal("999999"),
        )
        stt = trade_value * c.stt_bps / Decimal("10000") if side == Side.SELL else Decimal("0")
        exchange_fee = trade_value * c.exchange_fee_bps / Decimal("10000")
        sebi = trade_value * c.sebi_charges_bps / Decimal("10000")
        stamp = trade_value * c.stamp_duty_bps / Decimal("10000") if side == Side.BUY else Decimal("0")
        subtotal = brokerage + stt + exchange_fee + sebi + stamp
        gst = subtotal * c.gst_pct / Decimal("100")
        return _round4(subtotal + gst)


def _fill_price(ltp: Decimal, side: str, slippage_bps: Decimal) -> Decimal:
    factor = slippage_bps / Decimal("10000")
    if side == Side.BUY:
        return _round4(ltp * (1 + factor))
    return _round4(ltp * (1 - factor))


def _should_fill(order: Order, ltp: Decimal) -> bool:
    """Return True if this tick's LTP triggers a fill for the given order."""
    ot = order.order_type
    side = order.side
    if ot == OrderType.MARKET:
        return True
    if ot == OrderType.LIMIT:
        if side == Side.BUY:
            return ltp <= Decimal(str(order.price))
        return ltp >= Decimal(str(order.price))
    if ot in (OrderType.SL, OrderType.SL_M):
        tp = Decimal(str(order.trigger_price))
        if side == Side.BUY:
            return ltp >= tp
        return ltp <= tp
    return False


class PaperBroker:
    """
    Paper-fill engine.

    Subscribes to Redis pub/sub ``tick.<security_id>`` for all OPEN order securities.
    On each tick it checks every relevant OPEN order, applies fill logic, persists
    Trade/Order/Position rows, and publishes events to OrdersHub.
    """

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        slippage_bps: float,
    ) -> None:
        self._session_maker = session_maker
        self._slippage_bps = Decimal(str(slippage_bps))
        self._hub: OrdersHub | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        # in-memory cache: security_id -> list[Order] (OPEN orders)
        self._open_orders: dict[str, list[Order]] = {}
        # cached costs: instrument_type -> ChargesCalculator
        self._costs: dict[str, ChargesCalculator] = {}

    def set_hub(self, hub: OrdersHub) -> None:
        self._hub = hub

    async def start(self, redis: Redis) -> None:
        await self._load_open_orders()
        await self._load_costs()
        self._task = asyncio.create_task(
            self._run(redis), name="paper-broker"
        )
        log.info("paper_broker_started", open_orders=sum(len(v) for v in self._open_orders.values()))

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_order(self, order: Order) -> None:
        """Register a freshly-created OPEN order for tick monitoring."""
        sid = order.security_id
        if sid not in self._open_orders:
            self._open_orders[sid] = []
        self._open_orders[sid].append(order)

    async def cancel_order(self, order_id: int) -> None:
        """Remove an order from the in-memory watch list."""
        for orders in self._open_orders.values():
            for o in list(orders):
                if o.id == order_id:
                    orders.remove(o)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    async def _load_open_orders(self) -> None:
        from sqlalchemy.exc import ProgrammingError

        try:
            async with self._session_maker() as session:
                result = await session.execute(
                    select(Order).where(Order.status == OrderStatus.OPEN)
                )
                for order in result.scalars().all():
                    self._open_orders.setdefault(order.security_id, []).append(order)
        except ProgrammingError:
            log.warning("paper_broker_orders_table_missing", hint="run alembic upgrade head")

    async def _load_costs(self) -> None:
        from sqlalchemy.exc import ProgrammingError

        try:
            async with self._session_maker() as session:
                result = await session.execute(
                    select(BrokerCost).where(BrokerCost.broker == "paper")
                )
                for row in result.scalars().all():
                    self._costs[row.instrument_type] = ChargesCalculator(row)
        except ProgrammingError:
            log.warning("paper_broker_costs_table_missing", hint="run alembic upgrade head")

    async def _run(self, redis: Redis) -> None:
        pubsub = redis.pubsub()
        subscribed: set[str] = set()
        try:
            while not self._stop_event.is_set():
                # Subscribe incrementally to any newly-watched securities.
                new = set(self._open_orders.keys()) - subscribed
                if new:
                    await pubsub.subscribe(*(f"tick.{sid}" for sid in new))
                    subscribed |= new
                if not subscribed:
                    # Nothing to watch yet — wait instead of busy-spinning.
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=0.5)
                    except TimeoutError:
                        pass
                    continue
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )
                if message is None or message["type"] != "message":
                    continue
                await self._on_tick(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("paper_broker_run_error", exc=str(exc))
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _on_tick(self, message: dict[str, Any]) -> None:
        try:
            payload = json.loads(message["data"])
        except (json.JSONDecodeError, KeyError):
            return
        sid = payload.get("security_id", "")
        ltp_raw = payload.get("ltp")
        if ltp_raw is None or sid not in self._open_orders:
            return
        ltp = Decimal(str(ltp_raw))
        orders_to_fill = [o for o in self._open_orders.get(sid, []) if _should_fill(o, ltp)]
        for order in orders_to_fill:
            await self._fill(order, ltp, payload.get("exchange_segment", ""))

    async def _fill(self, order: Order, ltp: Decimal, exchange_segment: str) -> None:
        fp = _fill_price(ltp, order.side, self._slippage_bps)
        charges = self._compute_charges(order, fp)
        now = datetime.now(UTC)
        async with self._session_maker() as session:
            # 1. Create trade row
            trade = Trade(
                order_id=order.id,
                security_id=order.security_id,
                exchange_segment=order.exchange_segment or exchange_segment,
                side=order.side,
                qty=order.qty,
                fill_price=fp,
                slippage_bps=self._slippage_bps,
                charges=charges,
                filled_at=now,
            )
            session.add(trade)
            await session.flush()

            # 2. Transition order to FILLED
            await session.execute(
                update(Order)
                .where(Order.id == order.id)
                .values(status=OrderStatus.FILLED, filled_at=now)
            )

            # 3. Update position (upsert + weighted-avg / realize-on-reduce)
            position = await self._upsert_position(session, order, fp, now)

            await session.commit()
            await session.refresh(trade)

        # Remove from in-memory watch list
        sid_orders = self._open_orders.get(order.security_id, [])
        if order in sid_orders:
            sid_orders.remove(order)

        log.info(
            "paper_fill",
            order_id=order.id,
            security_id=order.security_id,
            fill_price=str(fp),
            charges=str(charges),
        )

        # 4. Publish events to WS hub
        if self._hub is not None:
            order.status = OrderStatus.FILLED
            order.filled_at = now
            self._hub.publish("order", _order_dict(order))
            self._hub.publish(
                "trade",
                {**_trade_dict(trade), "strategy_id": order.strategy_id},
            )
            if position is not None:
                self._hub.publish("position", _position_dict(position))

    async def _upsert_position(
        self,
        session: AsyncSession,
        order: Order,
        fill_price: Decimal,
        now: datetime,
    ) -> Position | None:
        return await upsert_position(session, order, fill_price, now)

    def _compute_charges(self, order: Order, fill_price: Decimal) -> Decimal:
        return compute_charges(self._costs, order, fill_price)


def compute_charges(
    costs: dict[str, ChargesCalculator],
    order: Order,
    fill_price: Decimal,
    qty: int | None = None,
) -> Decimal:
    """Compute charges for a fill from a ``broker_costs`` cache.

    Shared by the paper engine and the live Dhan broker. Picks the cost row by an
    exchange-segment heuristic (F&O / currency → derivatives, else equity).
    """
    # Ensure the cache has at least one row, else charges are zero.
    if not costs:
        return Decimal("0")
    seg = order.exchange_segment.upper()
    guessed = "FUTIDX" if ("FNO" in seg or "CUR" in seg) else "EQUITY"
    calc = costs.get(guessed)
    if calc is None:
        # Fall back to any available row.
        for itype in ("OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK", "EQUITY"):
            calc = costs.get(itype)
            if calc is not None:
                break
    if calc is None:
        return Decimal("0")
    return calc.compute(qty if qty is not None else order.qty, fill_price, order.side)


async def upsert_position(
    session: AsyncSession,
    order: Order,
    fill_price: Decimal,
    now: datetime,
) -> Position | None:
    """Upsert the position for ``order`` using weighted-average / realize-on-reduce.

    Shared by the paper engine and the live Dhan broker so P&L semantics match.
    """
    result = await session.execute(
        select(Position).where(
            Position.security_id == order.security_id,
            Position.exchange_segment == order.exchange_segment,
            Position.product == order.product,
        )
    )
    pos = result.scalar_one_or_none()
    qty = order.qty if order.side == Side.BUY else -order.qty
    if pos is None:
        pos = Position(
            security_id=order.security_id,
            exchange_segment=order.exchange_segment,
            product=order.product,
            net_qty=qty,
            avg_price=fill_price,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            updated_at=now,
        )
        session.add(pos)
    else:
        old_qty = pos.net_qty
        old_avg = pos.avg_price
        new_qty = old_qty + qty

        if new_qty == 0:
            # Fully closed
            realized = _round4((fill_price - old_avg) * Decimal(str(old_qty)))
            pos.realized_pnl += realized
            pos.avg_price = Decimal("0")
        elif (old_qty > 0 and qty > 0) or (old_qty < 0 and qty < 0):
            # Adding to position — weighted average
            total_cost = old_avg * Decimal(str(old_qty)) + fill_price * Decimal(str(order.qty))
            pos.avg_price = _round4(total_cost / Decimal(str(abs(new_qty))))
        else:
            # Reducing position
            reduce_qty = min(abs(qty), abs(old_qty))
            if old_qty > 0:
                realized = _round4((fill_price - old_avg) * Decimal(str(reduce_qty)))
            else:
                realized = _round4((old_avg - fill_price) * Decimal(str(reduce_qty)))
            pos.realized_pnl += realized

        pos.net_qty = new_qty
        pos.updated_at = now
    await session.flush()
    return pos


def _order_dict(o: Order) -> dict:
    return {
        "id": o.id,
        "client_order_id": o.client_order_id,
        "security_id": o.security_id,
        "side": o.side,
        "qty": o.qty,
        "order_type": o.order_type,
        "status": o.status,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
    }


def _trade_dict(t: Trade) -> dict:
    return {
        "id": t.id,
        "order_id": t.order_id,
        "security_id": t.security_id,
        "side": t.side,
        "qty": t.qty,
        "fill_price": str(t.fill_price),
        "charges": str(t.charges),
        "filled_at": t.filled_at.isoformat(),
    }


def _position_dict(p: Position) -> dict:
    return {
        "id": p.id,
        "security_id": p.security_id,
        "net_qty": p.net_qty,
        "avg_price": str(p.avg_price),
        "realized_pnl": str(p.realized_pnl),
        "unrealized_pnl": str(p.unrealized_pnl),
    }
