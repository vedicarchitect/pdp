"""Coverage + gap-radar API.

Prefix: /api/v1/coverage
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from pdp.settings import get_settings
from pdp.warehouse.coverage import all_coverage
from pdp.warehouse.service import UNDERLYING_REGISTRY
from pdp.warehouse.schemas import CoverageOut

router = APIRouter(prefix="/api/v1/coverage", tags=["Data Coverage"])

_DEFAULT_WINDOW_DAYS = 90


@router.get("", response_model=CoverageOut)
async def get_coverage(
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    underlying: str | None = Query(
        default=None, description="Limit to one underlying (NIFTY/BANKNIFTY/SENSEX)"
    ),
) -> CoverageOut:
    """Per-underlying, per-family coverage + gap-radar for a date window (default: last 90 days)."""
    if underlying is not None and underlying not in UNDERLYING_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported underlying: {underlying!r}. Supported: {sorted(UNDERLYING_REGISTRY)}",
        )

    window_to = date.fromisoformat(date_to) if date_to else date.today()
    window_from = (
        date.fromisoformat(date_from) if date_from else window_to - timedelta(days=_DEFAULT_WINDOW_DAYS)
    )

    settings = get_settings()
    mongo_db = request.app.state.mongo_db
    underlyings = [underlying] if underlying else None
    result = await all_coverage(
        mongo_db, settings, window_from=window_from, window_to=window_to, underlyings=underlyings
    )
    return CoverageOut(**result)
