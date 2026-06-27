"""REST API for broker account sync — manual trigger, run history, current-state reads."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.broker_sync.models import BrokerFund, BrokerHolding, BrokerPosition, BrokerSyncRun
from pdp.broker_sync.service import BrokerSyncService, _run_dict
from pdp.db.session import get_db

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/broker-sync", tags=["broker-sync"])


def _service(request: Request) -> BrokerSyncService:
    svc = getattr(request.app.state, "broker_sync_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="broker sync not enabled")
    return svc


@router.post("/run")
async def run_sync(
    request: Request,
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> dict[str, Any]:
    """Trigger a sync now (manual). Idempotent for a given date."""
    return await _service(request).run_daily(date, trigger="manual")


@router.get("/runs")
async def list_runs(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    rows = (
        await session.scalars(select(BrokerSyncRun).order_by(desc(BrokerSyncRun.started_at)).limit(limit))
    ).all()
    return {"runs": [_run_dict(r) for r in rows], "count": len(rows)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    run = await session.get(BrokerSyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_dict(run)


@router.get("/holdings")
async def get_holdings(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await session.scalars(select(BrokerHolding))).all()
    return {
        "holdings": [
            {
                "account_id": h.account_id, "security_id": h.security_id, "isin": h.isin,
                "symbol": h.symbol, "exchange": h.exchange, "total_qty": h.total_qty,
                "available_qty": h.available_qty, "avg_cost_price": str(h.avg_cost_price),
                "last_price": str(h.last_price) if h.last_price is not None else None,
            }
            for h in rows
        ],
        "count": len(rows),
    }


@router.get("/positions")
async def get_positions(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await session.scalars(select(BrokerPosition))).all()
    return {
        "positions": [
            {
                "account_id": p.account_id, "security_id": p.security_id,
                "exchange_segment": p.exchange_segment, "product_type": p.product_type,
                "symbol": p.symbol, "net_qty": p.net_qty, "buy_avg": str(p.buy_avg),
                "sell_avg": str(p.sell_avg), "realized_pnl": str(p.realized_pnl),
                "unrealized_pnl": str(p.unrealized_pnl),
            }
            for p in rows
        ],
        "count": len(rows),
    }


@router.get("/funds")
async def get_funds(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await session.scalars(select(BrokerFund))).all()
    return {
        "funds": [
            {
                "account_id": f.account_id, "available_balance": str(f.available_balance),
                "utilized_amount": str(f.utilized_amount),
                "collateral_amount": str(f.collateral_amount),
                "withdrawable_balance": str(f.withdrawable_balance),
            }
            for f in rows
        ],
        "count": len(rows),
    }
