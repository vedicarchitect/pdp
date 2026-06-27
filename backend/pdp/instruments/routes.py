from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db
from pdp.instruments import service
from pdp.instruments.schemas import InstrumentOut

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
async def list_instruments(
    q: str | None = Query(default=None, description="Symbol / underlying search"),
    segment: str | None = Query(default=None),
    instrument_type: str | None = Query(default=None),
    underlying: str | None = Query(default=None),
    expiry: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[InstrumentOut]:
    rows = await service.search(
        db,
        q=q,
        segment=segment,
        instrument_type=instrument_type,
        underlying=underlying,
        expiry=expiry,
        limit=limit,
    )
    return [InstrumentOut.model_validate(r) for r in rows]


@router.get("/{security_id}", response_model=InstrumentOut)
async def get_instrument(
    security_id: str,
    segment: str = Query(..., description="Exchange segment (e.g. NSE_EQ)"),
    db: AsyncSession = Depends(get_db),
) -> InstrumentOut:
    row = await service.get_by_id(db, security_id, segment)
    if row is None:
        raise HTTPException(status_code=404, detail="instrument not found")
    return InstrumentOut.model_validate(row)
