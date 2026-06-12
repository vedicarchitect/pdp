from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_IST = ZoneInfo("Asia/Kolkata")


def _ist_day_bounds() -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes spanning today in IST."""
    now_ist = datetime.now(tz=_IST)
    start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ist = start_ist + timedelta(days=1)
    return start_ist.astimezone(ZoneInfo("UTC")), end_ist.astimezone(ZoneInfo("UTC"))

from pdp.db.session import get_db
from pdp.orders.models import Order, OrderType, Position, Product, Side, Trade
from pdp.orders.router import select_broker

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["orders"])


# ------------------------------------------------------------------ #
# Request / response schemas                                          #
# ------------------------------------------------------------------ #

class OrderRequest(BaseModel):
    client_order_id: str | None = None
    security_id: str
    exchange_segment: str
    side: Side
    qty: int
    order_type: OrderType
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    product: Product
    strategy_id: str | None = None


def _add_mode_header(response: Response, request: Request) -> None:
    from pdp.settings import get_settings
    _, mode = select_broker(get_settings())
    response.headers["X-Trade-Mode"] = mode


def _order_out(o: Order) -> dict:
    return {
        "id": o.id,
        "client_order_id": o.client_order_id,
        "broker": o.broker,
        "mode": o.mode,
        "security_id": o.security_id,
        "exchange_segment": o.exchange_segment,
        "side": o.side,
        "qty": o.qty,
        "order_type": o.order_type,
        "price": str(o.price) if o.price is not None else None,
        "trigger_price": str(o.trigger_price) if o.trigger_price is not None else None,
        "product": o.product,
        "status": o.status,
        "placed_at": o.placed_at.isoformat() if o.placed_at else None,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
        "reject_reason": o.reject_reason,
        "strategy_id": o.strategy_id,
    }


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@router.post("/orders", status_code=201)
async def place_order(
    body: OrderRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    order_router = request.app.state.order_router
    order = await order_router.place_order(
        db,
        client_order_id=body.client_order_id,
        security_id=body.security_id,
        exchange_segment=body.exchange_segment,
        side=body.side,
        qty=body.qty,
        order_type=body.order_type,
        price=body.price,
        trigger_price=body.trigger_price,
        product=body.product,
        strategy_id=body.strategy_id,
    )
    # Idempotent: already existed → 200
    if body.client_order_id and order.client_order_id == body.client_order_id:
        response.status_code = 200
    _add_mode_header(response, request)
    return _order_out(order)


@router.get("/orders")
async def list_orders(
    response: Response,
    request: Request,
    status: Annotated[str | None, Query()] = None,
    today: Annotated[bool, Query()] = False,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(Order).order_by(Order.placed_at.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    if today:
        day_start, day_end = _ist_day_bounds()
        stmt = stmt.where(Order.placed_at >= day_start, Order.placed_at < day_end)
    result = await db.execute(stmt)
    _add_mode_header(response, request)
    return [_order_out(o) for o in result.scalars().all()]


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: int,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    order_router = request.app.state.order_router
    order = await order_router.cancel_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    _add_mode_header(response, request)
    return _order_out(order)


@router.get("/trades")
async def list_trades(
    response: Response,
    request: Request,
    security_id: Annotated[str | None, Query()] = None,
    today: Annotated[bool, Query()] = False,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(Trade).order_by(Trade.filled_at.desc())
    if security_id:
        stmt = stmt.where(Trade.security_id == security_id)
    if today:
        day_start, day_end = _ist_day_bounds()
        stmt = stmt.where(Trade.filled_at >= day_start, Trade.filled_at < day_end)
    result = await db.execute(stmt)
    _add_mode_header(response, request)
    return [
        {
            "id": t.id,
            "order_id": t.order_id,
            "security_id": t.security_id,
            "exchange_segment": t.exchange_segment,
            "side": t.side,
            "qty": t.qty,
            "fill_price": str(t.fill_price),
            "slippage_bps": str(t.slippage_bps),
            "charges": str(t.charges),
            "filled_at": t.filled_at.isoformat(),
        }
        for t in result.scalars().all()
    ]


@router.get("/positions")
async def list_positions(
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(select(Position).order_by(Position.security_id))
    _add_mode_header(response, request)
    return [
        {
            "id": p.id,
            "security_id": p.security_id,
            "exchange_segment": p.exchange_segment,
            "product": p.product,
            "net_qty": p.net_qty,
            "avg_price": str(p.avg_price),
            "realized_pnl": str(p.realized_pnl),
            "unrealized_pnl": str(p.unrealized_pnl),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in result.scalars().all()
    ]
