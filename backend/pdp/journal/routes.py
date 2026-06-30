from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


def _service(request: Request):
    return request.app.state.journal_service


@router.get("")
async def get_journal(request: Request, date: str | None = None) -> JSONResponse:
    return JSONResponse(content=_service(request).get_day(date))

@router.put("/{date}/metadata")
async def update_metadata(request: Request, date: str) -> JSONResponse:
    body = await request.json()
    notes = body.get("notes", "")
    tags = body.get("tags", [])
    screenshots = body.get("screenshots", [])
    await _service(request).update_metadata(date, notes, tags, screenshots)
    return JSONResponse(content={"status": "ok"})


@router.get("/stats")
async def get_journal_stats(request: Request, date: str | None = None) -> JSONResponse:
    return JSONResponse(content=_service(request).get_stats(date))

@router.get("/strategy/{strategy_id}")
async def get_strategy_stats(request: Request, strategy_id: str, date: str | None = None) -> JSONResponse:
    # Filter trades for this strategy and compute stats
    day_data = _service(request).get_day(date)
    trades = [t for t in day_data.get("trades", []) if t.get("strategy_id") == strategy_id]
    
    from pdp.journal.stats import compute_daily_stats
    return JSONResponse(content={"date": day_data.get("date"), "strategy_id": strategy_id, "stats": compute_daily_stats(trades)})
