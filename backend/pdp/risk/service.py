"""Kill-switch service and daily loss calculation helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.orders.models import Order, OrderStatus, OrderType, Position, Product, Side, Trade

log = structlog.get_logger()
_IST = ZoneInfo("Asia/Kolkata")

_INTRADAY_PRODUCTS = {Product.INTRADAY.value, Product.MIS.value}


class KillSwitchService:
    """Atomically cancel all open orders then flatten all intraday positions."""

    async def execute(
        self,
        session_maker: Any,
        order_router: Any,
        requester: dict[str, Any],
    ) -> dict[str, Any]:
        cancelled_orders: list[dict] = []
        flattened_positions: list[dict] = []
        errors: list[str] = []

        # --- Step 1: gather open order IDs ---
        async with session_maker() as session:
            result = await session.execute(
                select(Order.id, Order.security_id, Order.strategy_id).where(
                    Order.status == OrderStatus.OPEN
                )
            )
            open_rows = result.all()

        # --- Step 2: cancel each open order ---
        for row in open_rows:
            try:
                async with session_maker() as session:
                    order = await order_router.cancel_order(session, row.id)
                    if order is not None:
                        cancelled_orders.append({
                            "id": order.id,
                            "security_id": order.security_id,
                            "strategy_id": order.strategy_id,
                        })
            except Exception as exc:
                err = f"cancel_order {row.id}: {exc}"
                errors.append(err)
                log.warning("kill_switch_cancel_error", order_id=row.id, exc=str(exc))

        # --- Step 3: gather intraday positions with open qty ---
        async with session_maker() as session:
            result = await session.execute(
                select(Position).where(
                    Position.net_qty != 0,
                    Position.product.in_(list(_INTRADAY_PRODUCTS)),
                )
            )
            positions = result.scalars().all()
            pos_snapshots = [
                (p.security_id, p.exchange_segment, p.product, p.net_qty)
                for p in positions
            ]

        # --- Step 4: flatten each intraday position via market order ---
        for security_id, exchange_segment, product, net_qty in pos_snapshots:
            flatten_side = Side.SELL if net_qty > 0 else Side.BUY
            qty = abs(net_qty)
            try:
                async with session_maker() as session:
                    await order_router.place_order(
                        session,
                        client_order_id=None,
                        security_id=security_id,
                        exchange_segment=exchange_segment,
                        side=str(flatten_side),
                        qty=qty,
                        order_type=str(OrderType.MARKET),
                        price=None,
                        trigger_price=None,
                        product=product,
                        strategy_id=None,
                    )
                flattened_positions.append({
                    "security_id": security_id,
                    "exchange_segment": exchange_segment,
                    "product": product,
                    "qty_flattened": qty,
                    "side": str(flatten_side),
                })
            except Exception as exc:
                err = f"flatten {security_id}: {exc}"
                errors.append(err)
                log.warning("kill_switch_flatten_error", security_id=security_id, exc=str(exc))

        log.warning(
            "kill_switch_executed",
            requester=requester,
            cancelled_count=len(cancelled_orders),
            flattened_count=len(flattened_positions),
            error_count=len(errors),
            ts=datetime.now(UTC).isoformat(),
        )

        return {
            "status": "ok" if not errors else "partial",
            "cancelled_orders": cancelled_orders,
            "flattened_positions": flattened_positions,
            "errors": errors,
            "executed_at": datetime.now(UTC).isoformat(),
            "requester": requester,
        }


async def compute_daily_loss(session: AsyncSession, day_start_pnl: Decimal = Decimal("0")) -> dict[str, Any]:
    """Compute today's total P&L and per-strategy realized P&L from trades."""
    today_start = (
        datetime.now(_IST)
        .replace(hour=9, minute=15, second=0, microsecond=0)
        .astimezone(UTC)
    )

    # Total P&L from in-DB positions
    result = await session.execute(select(Position))
    positions = result.scalars().all()
    total_realized = sum((p.realized_pnl or Decimal("0")) for p in positions)
    total_unrealized = sum((p.unrealized_pnl or Decimal("0")) for p in positions)
    current_pnl = total_realized + total_unrealized
    day_pnl = current_pnl - day_start_pnl
    realized_loss_today = float(max(Decimal("0"), -day_pnl))

    # Per-strategy realized P&L from today's fills (via trades → orders)
    stmt = (
        select(
            Order.strategy_id,
            func.sum(
                case(
                    (Trade.side == Side.SELL, Trade.qty * Trade.fill_price),
                    else_=-(Trade.qty * Trade.fill_price),
                )
            ).label("realized_pnl"),
        )
        .join(Order, Trade.order_id == Order.id)
        .where(
            Trade.filled_at >= today_start,
            Order.strategy_id.is_not(None),
        )
        .group_by(Order.strategy_id)
    )
    result2 = await session.execute(stmt)
    per_strategy: dict[str, float] = {
        str(row.strategy_id): float(row.realized_pnl or 0) for row in result2
    }

    return {
        "total_realized_pnl": float(total_realized),
        "total_unrealized_pnl": float(total_unrealized),
        "day_pnl": float(day_pnl),
        "realized_loss_today": realized_loss_today,
        "per_strategy_realized_pnl": per_strategy,
    }
