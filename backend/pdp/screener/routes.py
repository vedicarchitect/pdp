from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

screener_router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


@screener_router.get("/run")
async def run_screener(strategy: str = "ema_alignment") -> JSONResponse:
    return JSONResponse(content={
        "results": [],
        "strategy": strategy,
        "note": "Screener engine not yet implemented.",
    })
