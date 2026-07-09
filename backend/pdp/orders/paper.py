from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
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
        # Redis client stored on start() so add_order() can fill MARKET orders immediately.
        self._redis: Redis | None = None

    def set_hub(self, hub: OrdersHub) -> None:
        self._hub = hub

    async def start(self, redis: Redis) -> None:
        self._redis = redis
        await self._load_open_orders()
        await self._load_costs()
        self._task = asyncio.create_task(self._run(redis), name="paper-broker")
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
        """Register a freshly-created OPEN order for tick monitoring.

        For MARKET orders, immediately attempts a fill from the Redis ``ltp:<sid>``
        cache so the strategy does not have to wait for the next pub/sub tick.  If no
        cached price is available the order stays OPEN and the pub/sub run-loop fills
        it on the next tick.
        """
        sid = order.security_id
        if sid not in self._open_orders:
            self._open_orders[sid] = []
        self._open_orders[sid].append(order)

        if order.order_type == OrderType.MARKET and self._redis is not None:
            raw = await self._redis.get(f"ltp:{sid}")
            if raw is not None:
                try:
                    ltp = Decimal(str(raw))
                    if ltp > Decimal("0"):
                        await self._fill(order, ltp, "")
                except Exception as exc:
                    log.warning("paper_immediate_fill_error", sid=sid, exc=str(exc))

    def notify_subscribe(self, security_id: str) -> None:
        """Pre-register security_id so the run-loop subscribes tick.{sid} immediately.

        Called from MarketControl.subscribe() before place_order() so the first tick
        after order placement fills the order rather than being missed.
        """
        if security_id not in self._open_orders:
            self._open_orders[security_id] = []

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
                result = await session.execute(select(Order).where(Order.status == OrderStatus.OPEN))
                for order in result.scalars().all():
                    self._open_orders.setdefault(order.security_id, []).append(order)
        except ProgrammingError:
            log.warning("paper_broker_orders_table_missing", hint="run alembic upgrade head")

    async def _load_costs(self) -> None:
        from sqlalchemy.exc import ProgrammingError

        try:
            async with self._session_maker() as session:
                result = await session.execute(select(BrokerCost).where(BrokerCost.broker == "paper"))
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
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
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
        if ltp <= Decimal("0"):
            # Ignore zero-price ticks — Dhan sends LTP=0 before the first real quote.
            # Filling at zero produces a bogus avg_price on the position.
            return
        orders_to_fill = [o for o in self._open_orders.get(sid, []) if _should_fill(o, ltp)]
        for order in orders_to_fill:
            await self._fill(order, ltp, payload.get("exchange_segment", ""))

    async def _fill(self, order: Order, ltp: Decimal, exchange_segment: str) -> None:
        if order.status == OrderStatus.FILLED:
            # Already booked — duplicate tick or immediate-fill race; skip silently.
            return
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
                update(Order).where(Order.id == order.id).values(status=OrderStatus.FILLED, filled_at=now)
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


@dataclass
class PositionUpdate:
    """Result of compute_position_update: new position state after one fill."""

    new_qty: int
    new_avg: Decimal
    realized_delta: Decimal  # P&L booked on the closed portion (positive = gain)


def compute_position_update(
    old_qty: int,
    old_avg: Decimal,
    fill_qty: int,
    fill_price: Decimal,
) -> PositionUpdate:
    """Pure function: compute new (net_qty, avg_price, realized_delta) from one fill.

    Handles all four cases branch-free:
    * New position (old_qty == 0)          → avg_price = fill_price
    * Adding to same-side (sign match)     → weighted average
    * Reducing but not through zero        → realize on closed qty; avg unchanged
    * Reversal through zero or flat reopen → realize on closed qty; re-base avg to fill_price

    Shared by PaperBroker and DhanBroker so P&L semantics are identical everywhere.
    """
    new_qty = old_qty + fill_qty

    # Case 1: fully closed → zero the position
    if new_qty == 0:
        realized = Decimal("0")
        if old_avg != Decimal("0") and old_qty != 0:
            realized = _round4((fill_price - old_avg) * Decimal(str(old_qty)))
        return PositionUpdate(new_qty=0, new_avg=Decimal("0"), realized_delta=realized)

    # Case 2: new position from flat (old_qty == 0) → re-base avg
    if old_qty == 0:
        return PositionUpdate(new_qty=new_qty, new_avg=fill_price, realized_delta=Decimal("0"))

    # Case 3: adding to same-side position → weighted average
    same_side = (old_qty > 0 and fill_qty > 0) or (old_qty < 0 and fill_qty < 0)
    if same_side:
        total_cost = old_avg * Decimal(str(abs(old_qty))) + fill_price * Decimal(str(abs(fill_qty)))
        new_avg = _round4(total_cost / Decimal(str(abs(new_qty))))
        return PositionUpdate(new_qty=new_qty, new_avg=new_avg, realized_delta=Decimal("0"))

    # Case 4: reducing / reversing through zero
    close_qty = min(abs(fill_qty), abs(old_qty))
    realized = Decimal("0")
    if old_avg != Decimal("0"):
        if old_qty > 0:
            realized = _round4((fill_price - old_avg) * Decimal(str(close_qty)))
        else:
            realized = _round4((old_avg - fill_price) * Decimal(str(close_qty)))

    # Sign flipped → re-base avg to fill_price for the residual leg
    sign_flipped = (old_qty > 0) != (new_qty > 0)
    new_avg = fill_price if sign_flipped else old_avg
    return PositionUpdate(new_qty=new_qty, new_avg=new_avg, realized_delta=realized)


async def upsert_position(
    session: AsyncSession,
    order: Order,
    fill_price: Decimal,
    now: datetime,
) -> Position | None:
    """Upsert the position for ``order`` using compute_position_update.

    Shared by the paper engine and the live Dhan broker so P&L semantics match.
    Delegates all avg_price / realized_pnl logic to the pure helper so there is
    a single source of truth across flat-reopen, same-side add, reduce, and reversal.
    """
    result = await session.execute(
        select(Position).where(
            Position.strategy_id == order.strategy_id,
            Position.security_id == order.security_id,
            Position.exchange_segment == order.exchange_segment,
            Position.product == order.product,
        )
    )
    pos = result.scalar_one_or_none()
    fill_qty = order.qty if order.side == Side.BUY else -order.qty
    if pos is None:
        pos = Position(
            strategy_id=order.strategy_id,
            security_id=order.security_id,
            exchange_segment=order.exchange_segment,
            product=order.product,
            net_qty=fill_qty,
            avg_price=fill_price,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            updated_at=now,
        )
        session.add(pos)
    else:
        old_qty = pos.net_qty
        old_avg = pos.avg_price
        if old_avg == Decimal("0") and old_qty != 0:
            log.warning(
                "zero_avg_realized_skipped",
                security_id=order.security_id,
                strategy_id=order.strategy_id,
            )
        update = compute_position_update(old_qty, old_avg, fill_qty, fill_price)
        pos.net_qty = update.new_qty
        pos.avg_price = update.new_avg
        pos.realized_pnl += update.realized_delta
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
