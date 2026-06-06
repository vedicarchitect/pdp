"""Portfolio REST endpoints."""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db
from pdp.orders.models import Position

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


def _pos_dict(p: Position) -> dict:
    return {
        "security_id": p.security_id,
        "exchange_segment": p.exchange_segment,
        "product": p.product,
        "net_qty": p.net_qty,
        "avg_price": str(p.avg_price),
        "realized_pnl": str(p.realized_pnl),
        "unrealized_pnl": str(p.unrealized_pnl),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/positions")
async def get_positions(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    result = await db.execute(select(Position))
    positions = result.scalars().all()
    dicts = [_pos_dict(p) for p in positions]
    return JSONResponse({"positions": dicts, "count": len(dicts)})


@router.get("/summary")
async def get_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    from pdp.settings import get_settings

    result = await db.execute(select(Position))
    positions = result.scalars().all()

    from decimal import Decimal

    total_unrealized = sum((p.unrealized_pnl or Decimal("0")) for p in positions)
    total_realized = sum((p.realized_pnl or Decimal("0")) for p in positions)
    open_count = sum(1 for p in positions if p.net_qty != 0)

    settings = get_settings()
    mode = "live" if settings.LIVE else "paper"

    return JSONResponse(
        {
            "total_unrealized_pnl": float(total_unrealized),
            "total_realized_pnl": float(total_realized),
            "day_pnl": float(total_unrealized + total_realized),
            "open_positions": open_count,
            "mode": mode,
        }
    )
