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
from pdp.deps import require_auth, PaginationParams
from pdp.broker_sync.schemas import BrokerSyncRunOut, BrokerHoldingOut, BrokerPositionOut, BrokerFundOut
from pdp.schemas import Page

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/broker-sync", tags=["broker-sync"])


def _service(request: Request) -> BrokerSyncService:
    svc = getattr(request.app.state, "broker_sync_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="broker sync not enabled")
    return svc


@router.post(
    "/run",
    response_model=BrokerSyncRunOut,
    status_code=202,
    dependencies=[Depends(require_auth)],
    summary="Run broker sync",
    description="Trigger a sync now (manual). Idempotent for a given date.",
)
async def run_sync(
    request: Request,
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> BrokerSyncRunOut:
    """Trigger a sync now (manual). Idempotent for a given date."""
    result = await _service(request).run_daily(date, trigger="manual")
    return BrokerSyncRunOut(**result)


@router.get("/runs", response_model=Page[BrokerSyncRunOut])
async def list_runs(
    session: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
) -> Page[BrokerSyncRunOut]:
    rows = (
        await session.scalars(
            select(BrokerSyncRun)
            .order_by(desc(BrokerSyncRun.started_at))
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).all()
    items = [BrokerSyncRunOut(**_run_dict(r)) for r in rows]
    return Page(items=items, limit=pagination.limit, offset=pagination.offset)


@router.get("/runs/{run_id}", response_model=BrokerSyncRunOut)
async def get_run(run_id: str, session: AsyncSession = Depends(get_db)) -> BrokerSyncRunOut:
    run = await session.get(BrokerSyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return BrokerSyncRunOut(**_run_dict(run))


@router.get("/holdings", response_model=Page[BrokerHoldingOut])
async def get_holdings(
    session: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
) -> Page[BrokerHoldingOut]:
    rows = (await session.scalars(select(BrokerHolding).offset(pagination.offset).limit(pagination.limit))).all()
    items = [
        BrokerHoldingOut(
            account_id=h.account_id,
            security_id=h.security_id,
            isin=h.isin,
            symbol=h.symbol,
            exchange=h.exchange,
            total_qty=h.total_qty,
            available_qty=h.available_qty,
            avg_cost_price=str(h.avg_cost_price),
            last_price=str(h.last_price) if h.last_price is not None else None,
            last_synced_at=h.synced_at.isoformat() if h.synced_at else None,
        )
        for h in rows
    ]
    return Page(items=items, limit=pagination.limit, offset=pagination.offset)


@router.get("/positions", response_model=Page[BrokerPositionOut])
async def get_positions(
    session: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
) -> Page[BrokerPositionOut]:
    rows = (await session.scalars(select(BrokerPosition).offset(pagination.offset).limit(pagination.limit))).all()
    items = [
        BrokerPositionOut(
            account_id=p.account_id,
            security_id=p.security_id,
            exchange_segment=p.exchange_segment,
            product_type=p.product_type,
            symbol=p.symbol,
            net_qty=p.net_qty,
            buy_avg=str(p.buy_avg),
            sell_avg=str(p.sell_avg),
            realized_pnl=str(p.realized_pnl),
            unrealized_pnl=str(p.unrealized_pnl),
            last_synced_at=p.synced_at.isoformat() if p.synced_at else None,
        )
        for p in rows
    ]
    return Page(items=items, limit=pagination.limit, offset=pagination.offset)


@router.get("/funds", response_model=Page[BrokerFundOut])
async def get_funds(
    session: AsyncSession = Depends(get_db),
    pagination: PaginationParams = Depends(),
) -> Page[BrokerFundOut]:
    rows = (await session.scalars(select(BrokerFund).offset(pagination.offset).limit(pagination.limit))).all()
    items = [
        BrokerFundOut(
            account_id=f.account_id,
            available_balance=str(f.available_balance),
            utilized_amount=str(f.utilized_amount),
            collateral_amount=str(f.collateral_amount),
            withdrawable_balance=str(f.withdrawable_balance),
            last_synced_at=f.synced_at.isoformat() if f.synced_at else None,
        )
        for f in rows
    ]
    return Page(items=items, limit=pagination.limit, offset=pagination.offset)
