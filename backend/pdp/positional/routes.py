"""Positional monitor REST endpoints — EOD snapshot storage and history."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db
from pdp.mongo.collections import get_positional_snapshots_collection
from pdp.orders.models import Position
from pdp.positional.models import PositionalSnapshotDocument
from pdp.settings import get_settings
from pdp.positional.schemas import PositionalSnapshotOut

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/positional", tags=["positional"])


def _get_mongo_db(request: Request) -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    return request.app.state.mongo_db


@router.post(
    "/snapshot",
    response_model=PositionalSnapshotOut,
    status_code=201,
    summary="Create EOD snapshot",
    description="Captures and stores the end-of-day portfolio snapshot.",
)
async def create_snapshot(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PositionalSnapshotOut:
    settings = get_settings()
    mongo_db = _get_mongo_db(request)
    col = get_positional_snapshots_collection(mongo_db)

    result = await db.execute(select(Position))
    positions = result.scalars().all()

    total_unrealized = float(sum((p.unrealized_pnl or Decimal("0")) for p in positions))
    total_realized = float(sum((p.realized_pnl or Decimal("0")) for p in positions))
    day_pnl = total_unrealized + total_realized
    open_count = sum(1 for p in positions if p.net_qty != 0)
    mode = "live" if settings.LIVE else "paper"
    today = date.today().isoformat()

    doc = PositionalSnapshotDocument(
        date=today,
        total_unrealized_pnl=total_unrealized,
        total_realized_pnl=total_realized,
        day_pnl=day_pnl,
        position_count=open_count,
        created_at=datetime.now(UTC),
        mode=mode,
    )
    doc_dict = doc.model_dump()
    await col.update_one({"date": today}, {"$set": doc_dict}, upsert=True)

    log.info("positional_snapshot_created", date=today, day_pnl=day_pnl, mode=mode)
    return PositionalSnapshotOut(**doc_dict)


@router.get("/snapshots", response_model=list[PositionalSnapshotOut])
async def get_snapshots(
    request: Request,
    days: int = Query(default=90, ge=1, le=365),
) -> list[PositionalSnapshotOut]:
    mongo_db = _get_mongo_db(request)
    col = get_positional_snapshots_collection(mongo_db)

    cursor = col.find({}, {"_id": 0}).sort("date", 1).limit(days)
    docs = await cursor.to_list(length=days)

    for doc in docs:
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()

    return [PositionalSnapshotOut(**doc) for doc in docs]
