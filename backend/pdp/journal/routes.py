from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])

_IST = ZoneInfo("Asia/Kolkata")


def _service(request: Request):
    return request.app.state.journal_service


def _running_strangle_ids(request: Request) -> list[str]:
    from pdp.strategies.directional_strangle import DirectionalStrangle

    host = getattr(request.app.state, "strategy_host", None)
    if host is None:
        return []
    return [
        sid for sid, state in host._running.items()
        if isinstance(state.instance, DirectionalStrangle)
    ]


@router.get("")
async def get_journal(request: Request, date: str | None = None) -> JSONResponse:
    """Journal day view.

    For days with strangle activity, `by_index`/`stats.realized_pnl` are derived
    from the same entry→exit ledger as `/strangle/trades` (task 4.3) — realized
    P&L for a day+strategy MUST match across both surfaces. Non-strangle fills
    still populate the legacy `trades` list.
    """
    day_data = _service(request).get_day(date)

    strangle_ids = _running_strangle_ids(request)
    if strangle_ids:
        from pdp.strategy.trade_ledger import (
            compute_totals,
            group_by_index,
            pair_trades,
            read_day_events,
        )

        query_date = date_type.fromisoformat(date) if date else datetime.now(_IST).date()
        all_rows = []
        for sid in strangle_ids:
            all_rows.extend(pair_trades(read_day_events(sid, query_date)))

        if all_rows:
            totals = compute_totals(all_rows)
            day_data["by_index"] = group_by_index(all_rows)
            day_data["totals"] = totals
            day_data["stats"] = {
                **day_data["stats"],
                "realized_pnl": totals["realized_pnl"],
                "round_trips": totals["n_round_trips"],
            }

    return JSONResponse(content=day_data)

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
    if strategy_id in _running_strangle_ids(request):
        from pdp.strategy.trade_ledger import (
            compute_totals,
            group_by_index,
            pair_trades,
            read_day_events,
        )

        query_date = date_type.fromisoformat(date) if date else datetime.now(_IST).date()
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
    return JSONResponse(content={
        "date": day_data.get("date"),
        "strategy_id": strategy_id,
        "stats": compute_daily_stats(trades),
    })
