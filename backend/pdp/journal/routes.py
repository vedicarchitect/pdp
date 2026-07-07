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
    """Per-strategy daily stats.

    For strangle strategies, derives realized P&L from the enriched entry→exit
    ledger (same source as /strangle/trades) so the two surfaces always agree.
    For non-strangle strategies, falls back to the traditional fill-based stats.
    """
    from pdp.strategies.directional_strangle import DirectionalStrangle

    # Check if this strategy_id belongs to a running strangle instance
    host = request.app.state.strategy_host
    is_strangle = any(
        isinstance(state.instance, DirectionalStrangle) and sid == strategy_id
        for sid, state in host._running.items()
    )

    if is_strangle:
        from datetime import date as date_type
        from zoneinfo import ZoneInfo

        from pdp.strategy.trade_ledger import (
            compute_totals,
            group_by_index,
            pair_trades,
            read_day_events,
        )

        _ist = ZoneInfo("Asia/Kolkata")
        from datetime import datetime

        query_date = date_type.fromisoformat(date) if date else datetime.now(_ist).date()
        events = read_day_events(strategy_id, query_date)
        rows = pair_trades(events)
        by_index = group_by_index(rows)
        totals = compute_totals(rows)
        return JSONResponse(content={
            "date": query_date.isoformat(),
            "strategy_id": strategy_id,
            "by_index": by_index,
            "totals": totals,
            "trades": rows,
        })

    # Non-strangle: fall back to traditional fill-based stats
    day_data = _service(request).get_day(date)
    trades = [t for t in day_data.get("trades", []) if t.get("strategy_id") == strategy_id]

    from pdp.journal.stats import compute_daily_stats
    return JSONResponse(content={"date": day_data.get("date"), "strategy_id": strategy_id, "stats": compute_daily_stats(trades)})
