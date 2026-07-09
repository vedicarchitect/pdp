from __future__ import annotations

from fastapi import APIRouter
from pdp.screener.schemas import ScreenerOut

screener_router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


@screener_router.get("/run", response_model=ScreenerOut)
async def run_screener(strategy: str = "ema_alignment") -> ScreenerOut:
    return ScreenerOut(
        results=[],
        strategy=strategy,
        note="Screener engine not yet implemented.",
    )
