from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db
from pdp.market.subscription_model import Subscription

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["market"])


class Timeframe(StrEnum):
    m1 = "1m"
    m5 = "5m"
    m15 = "15m"
    m30 = "30m"
    h1 = "1H"


def _get_adapter(request: Request):
    adapter = getattr(request.app.state, "dhan_adapter", None)
    if adapter is None:
        raise HTTPException(status_code=503, detail="market feed not configured")
    return adapter


@router.get("/ltp")
async def get_ltp(
    request: Request,
    ids: Annotated[str, Query(description="Comma-separated security IDs")],
) -> dict[str, float | None]:
    """Return latest LTP per security from Redis hot cache."""
    redis = request.app.state.redis
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        return {}
    keys = [f"ltp:{sid}" for sid in id_list]
    values = await redis.mget(*keys)
    return {sid: float(v) if v is not None else None for sid, v in zip(id_list, values, strict=True)}


@router.post("/subscriptions")
async def add_subscription(
    request: Request,
    security_id: str,
    exchange_segment: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Subscribe the market feed adapter to a security."""
    adapter = _get_adapter(request)
    ok = await adapter.subscribe(security_id, exchange_segment, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"unknown segment: {exchange_segment}")
    return {"status": "subscribed", "security_id": security_id, "exchange_segment": exchange_segment}


@router.delete("/subscriptions/{security_id}")
async def remove_subscription(
    request: Request,
    security_id: str,
    exchange_segment: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Unsubscribe the market feed adapter from a security."""
    adapter = _get_adapter(request)
    await adapter.unsubscribe(security_id, exchange_segment, db)
    return {"status": "unsubscribed", "security_id": security_id}


@router.get("/bars/{security_id}")
async def get_bars(
    request: Request,
    security_id: str,
    tf: Timeframe,
    limit: Annotated[int, Query(ge=1, le=2000)] = 375,
) -> list[dict]:
    """Return the most recent N closed bars for a security from MongoDB."""
    collection = request.app.state.mongo_db["market_bars"]
    cursor = collection.find(
        {"metadata.security_id": security_id, "metadata.timeframe": tf.value},
        sort=[("ts", -1)],
        limit=limit,
    )
    return [
        {
            "security_id": doc["metadata"]["security_id"],
            "timeframe": doc["metadata"]["timeframe"],
            "bar_time": doc["ts"].isoformat(),
            "open": str(doc["open"]),
            "high": str(doc["high"]),
            "low": str(doc["low"]),
            "close": str(doc["close"]),
            "volume": doc["volume"],
            "oi": doc["oi"],
        }
        async for doc in cursor
    ]


@router.get("/subscriptions")
async def list_subscriptions(db: AsyncSession = Depends(get_db)) -> list[dict[str, str]]:
    result = await db.execute(select(Subscription).order_by(Subscription.added_at))
    rows = result.scalars().all()
    return [{"security_id": r.security_id, "exchange_segment": r.exchange_segment} for r in rows]
