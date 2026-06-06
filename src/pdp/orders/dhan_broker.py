from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select, update

from pdp.orders.models import BrokerCost, Order, OrderStatus, Trade
from pdp.orders.paper import (
    ChargesCalculator,
    _order_dict,
    _position_dict,
    _round4,
    _trade_dict,
    compute_charges,
    upsert_position,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.orders.ws import OrdersHub
    from pdp.settings import Settings

log = structlog.get_logger()

# Platform order field → Dhan SDK parameter value
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOP_LOSS",
    "SL_M": "STOP_LOSS_MARKET",
}
_PRODUCT_MAP = {
    "NRML": "MARGIN",
    "MIS": "INTRADAY",
    "INTRADAY": "INTRADAY",
    "DELIVERY": "CNC",
    "CNC": "CNC",
}
# Most segments pass through unchanged (NSE_EQ, NSE_FNO, BSE_EQ, ...); only
# currency segments differ between the market-feed labels and the order API.
_SEGMENT_MAP = {
    "NSE_CUR": "NSE_CURRENCY",
    "BSE_CUR": "BSE_CURRENCY",
}

_MAX_RECONNECT_DELAY = 30.0


def _to_dhan_params(order: Order) -> dict[str, Any]:
    """Map a platform :class:`Order` to ``dhanhq.place_order`` keyword arguments."""
    return {
        "security_id": order.security_id,
        "exchange_segment": _SEGMENT_MAP.get(order.exchange_segment, order.exchange_segment),
        "transaction_type": order.side,  # BUY / SELL — direct
        "quantity": order.qty,
        "order_type": _ORDER_TYPE_MAP.get(order.order_type, order.order_type),
        "product_type": _PRODUCT_MAP.get(order.product, order.product),
        "price": float(order.price) if order.price is not None else 0.0,
        "trigger_price": float(order.trigger_price) if order.trigger_price is not None else 0.0,
        "tag": order.client_order_id or None,
    }


def _remarks_str(remarks: Any) -> str:
    if isinstance(remarks, dict):
        return str(remarks.get("error_message") or remarks)
    return str(remarks) if remarks else "rejected by broker"


class DhanBroker:
    """
    Live order adapter for Dhan.

    Mirrors the :class:`~pdp.orders.paper.PaperBroker` interface so the
    ``OrderRouter`` selects it purely on the order's ``broker`` field. The
    ``dhanhq`` REST SDK is synchronous, so every call is offloaded to a thread
    pool; live fills arrive over Dhan's async order-update WebSocket and are
    converted to ``Trade`` / ``Position`` rows reusing the paper accounting.
    """

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._session_maker = session_maker
        self._client_id = settings.DHAN_CLIENT_ID
        self._access_token = settings.DHAN_ACCESS_TOKEN
        self._hub: OrdersHub | None = None
        self._client: Any = None  # dhanhq client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._costs: dict[str, ChargesCalculator] = {}
        self._order_update: Any = None
        self._ou_task: asyncio.Task[None] | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._stop_event = asyncio.Event()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="dhan-rest"
        )

    def set_hub(self, hub: OrdersHub) -> None:
        self._hub = hub

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self, redis: Redis | None = None) -> None:
        from dhanhq import DhanContext, OrderUpdate, dhanhq

        self._loop = asyncio.get_running_loop()
        ctx = DhanContext(self._client_id, self._access_token)
        self._client = dhanhq(ctx)
        await self._load_costs()
        await self._reconcile()
        self._order_update = OrderUpdate(ctx)
        self._order_update.on_update = self._on_alert
        self._ou_task = asyncio.create_task(
            self._order_update_loop(), name="dhan-order-update"
        )
        log.info("dhan_broker_started", client_id=self._client_id)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._ou_task is not None:
            self._ou_task.cancel()
            try:
                await self._ou_task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    # OrderRouter interface                                                #
    # ------------------------------------------------------------------ #

    async def add_order(self, order: Order) -> None:
        """Place ``order`` on Dhan and persist the returned broker order id."""
        params = _to_dhan_params(order)
        resp = await self._call(self._client.place_order, **params)
        if not isinstance(resp, dict) or resp.get("status") != "success":
            reason = _remarks_str(resp.get("remarks") if isinstance(resp, dict) else resp)
            await self._mark_rejected(order.id, reason)
            log.warning("dhan_place_failed", order_id=order.id, reason=reason)
            return
        broker_order_id = str(resp["data"]["orderId"])
        await self._store_broker_order_id(order.id, broker_order_id)
        log.info(
            "dhan_order_placed",
            order_id=order.id,
            broker_order_id=broker_order_id,
            security_id=order.security_id,
        )

    async def cancel_order(self, order_id: int) -> None:
        broker_order_id = await self._get_broker_order_id(order_id)
        if broker_order_id is None:
            log.warning("dhan_cancel_no_broker_id", order_id=order_id)
            return
        resp = await self._call(self._client.cancel_order, broker_order_id)
        status = resp.get("status") if isinstance(resp, dict) else "unknown"
        log.info(
            "dhan_cancel", order_id=order_id, broker_order_id=broker_order_id, status=status
        )

    # ------------------------------------------------------------------ #
    # Order-update stream                                                  #
    # ------------------------------------------------------------------ #

    async def _order_update_loop(self) -> None:
        delay = 1.0
        while not self._stop_event.is_set():
            try:
                await self._order_update.connect_order_update()
                delay = 1.0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("dhan_order_update_error", exc=str(exc), retry_in=delay)
            if self._stop_event.is_set():
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    def _on_alert(self, update: dict[str, Any]) -> None:
        """SDK callback (runs inside the event loop) — schedule async handling."""
        data = update.get("Data") or update.get("data") or update
        broker_order_id = data.get("orderNo") or data.get("orderId")
        status = str(data.get("status", "")).upper()
        if not broker_order_id:
            return
        # Keep a reference so the task isn't garbage-collected mid-flight.
        task = asyncio.create_task(self._handle_alert(str(broker_order_id), status))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _handle_alert(self, broker_order_id: str, status: str) -> None:
        try:
            if status == "TRADED":
                await self._fill(broker_order_id)
            elif status in ("CANCELLED", "CANCELED"):
                await self._transition(broker_order_id, OrderStatus.CANCELLED, cancelled=True)
            elif status == "REJECTED":
                await self._transition(broker_order_id, OrderStatus.REJECTED)
        except Exception as exc:
            log.error("dhan_handle_alert_error", broker_order_id=broker_order_id, exc=str(exc))

    async def _fill(self, broker_order_id: str) -> None:
        """Convert a TRADED alert into a Trade + Position using the trade book."""
        resp = await self._call(self._client.get_trade_book, broker_order_id)
        if not isinstance(resp, dict) or resp.get("status") != "success":
            log.warning("dhan_trade_book_failed", broker_order_id=broker_order_id)
            return
        trades_data = resp.get("data") or []
        if isinstance(trades_data, dict):
            trades_data = [trades_data]

        total_qty = 0
        total_value = Decimal("0")
        for t in trades_data:
            q = int(t.get("tradedQuantity") or t.get("filledQty") or 0)
            p = Decimal(str(t.get("tradedPrice") or t.get("price") or 0))
            total_qty += q
            total_value += p * Decimal(q)
        if total_qty == 0:
            log.warning("dhan_trade_book_empty", broker_order_id=broker_order_id)
            return
        avg_price = _round4(total_value / Decimal(total_qty))
        now = datetime.now(UTC)

        async with self._session_maker() as session:
            order = await self._order_by_broker_id(session, broker_order_id)
            if order is None:
                log.warning("dhan_fill_unknown_order", broker_order_id=broker_order_id)
                return
            if order.status == OrderStatus.FILLED:
                return  # idempotent — already recorded

            # v1: a TRADED alert is treated as a full fill (partial-fill splitting
            # is a documented non-goal). Trade price comes from the broker.
            charges = compute_charges(self._costs, order, avg_price)
            trade = Trade(
                order_id=order.id,
                security_id=order.security_id,
                exchange_segment=order.exchange_segment,
                side=order.side,
                qty=order.qty,
                fill_price=avg_price,
                slippage_bps=Decimal("0"),
                charges=charges,
                filled_at=now,
            )
            session.add(trade)
            await session.flush()

            await session.execute(
                update(Order)
                .where(Order.id == order.id)
                .values(status=OrderStatus.FILLED, filled_at=now)
            )
            position = await upsert_position(session, order, avg_price, now)
            await session.commit()
            await session.refresh(trade)

        log.info(
            "dhan_fill",
            order_id=order.id,
            broker_order_id=broker_order_id,
            fill_price=str(avg_price),
            charges=str(charges),
        )
        if self._hub is not None:
            order.status = OrderStatus.FILLED
            order.filled_at = now
            self._hub.publish("order", _order_dict(order))
            self._hub.publish("trade", _trade_dict(trade))
            if position is not None:
                self._hub.publish("position", _position_dict(position))

    async def _transition(
        self, broker_order_id: str, status: str, *, cancelled: bool = False
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_maker() as session:
            order = await self._order_by_broker_id(session, broker_order_id)
            if order is None or order.status in (OrderStatus.FILLED, status):
                return
            values: dict[str, Any] = {"status": status}
            if cancelled:
                values["cancelled_at"] = now
            await session.execute(update(Order).where(Order.id == order.id).values(**values))
            await session.commit()
            order.status = status
        if self._hub is not None:
            self._hub.publish("order", _order_dict(order))
        log.info("dhan_order_transition", broker_order_id=broker_order_id, status=status)

    # ------------------------------------------------------------------ #
    # Startup reconciliation                                               #
    # ------------------------------------------------------------------ #

    async def _reconcile(self) -> None:
        """Apply fills/cancellations that occurred while the process was down."""
        async with self._session_maker() as session:
            result = await session.execute(
                select(Order).where(
                    Order.broker == "dhan",
                    Order.status == OrderStatus.OPEN,
                    Order.broker_order_id.is_not(None),
                )
            )
            open_orders = list(result.scalars().all())
        if not open_orders:
            return
        resp = await self._call(self._client.get_order_list)
        order_list = resp.get("data") or [] if isinstance(resp, dict) else []
        status_by_id = {
            str(o.get("orderId")): str(o.get("orderStatus", "")).upper() for o in order_list
        }
        for order in open_orders:
            boid = order.broker_order_id
            if boid is None:
                continue
            broker_status = status_by_id.get(boid)
            if broker_status == "TRADED":
                await self._fill(boid)
            elif broker_status in ("CANCELLED", "CANCELED"):
                await self._transition(boid, OrderStatus.CANCELLED, cancelled=True)
            elif broker_status == "REJECTED":
                await self._transition(boid, OrderStatus.REJECTED)
        log.info("dhan_reconciled", open_orders=len(open_orders))

    # ------------------------------------------------------------------ #
    # DB + executor helpers                                                #
    # ------------------------------------------------------------------ #

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        loop = self._loop or asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    async def _load_costs(self) -> None:
        from sqlalchemy.exc import ProgrammingError

        try:
            async with self._session_maker() as session:
                result = await session.execute(
                    select(BrokerCost).where(BrokerCost.broker == "dhan")
                )
                for row in result.scalars().all():
                    self._costs[row.instrument_type] = ChargesCalculator(row)
        except ProgrammingError:
            log.warning("dhan_broker_costs_table_missing", hint="run alembic upgrade head")

    async def _store_broker_order_id(self, order_id: int, broker_order_id: str) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(Order)
                .where(Order.id == order_id)
                .values(broker_order_id=broker_order_id)
            )
            await session.commit()

    async def _mark_rejected(self, order_id: int, reason: str) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(Order)
                .where(Order.id == order_id)
                .values(status=OrderStatus.REJECTED, reject_reason=reason)
            )
            await session.commit()
        if self._hub is not None:
            async with self._session_maker() as session:
                order = (
                    await session.execute(select(Order).where(Order.id == order_id))
                ).scalar_one_or_none()
            if order is not None:
                self._hub.publish("order", _order_dict(order))

    async def _get_broker_order_id(self, order_id: int) -> str | None:
        async with self._session_maker() as session:
            result = await session.execute(
                select(Order.broker_order_id).where(Order.id == order_id)
            )
            row = result.first()
        return row[0] if row else None

    async def _order_by_broker_id(
        self, session: AsyncSession, broker_order_id: str
    ) -> Order | None:
        result = await session.execute(
            select(Order).where(Order.broker_order_id == broker_order_id)
        )
        return result.scalar_one_or_none()
