from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from pdp.deps import parse_ist_date, require_auth
from pdp.journal.schemas import JournalDayOut, StatusOut, JournalStrategyStatsOut

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


class JournalMetadata(BaseModel):
    """Validated request body for journal metadata edits."""

    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


def _service(request: Request):
    return request.app.state.journal_service


def _running_strangle_ids(request: Request) -> list[str]:
    from pdp.strategies.directional_strangle import DirectionalStrangle

    host = getattr(request.app.state, "strategy_host", None)
    if host is None:
        return []
    return [sid for sid, state in host._running.items() if isinstance(state.instance, DirectionalStrangle)]


@router.get("", response_model=JournalDayOut)
async def get_journal(request: Request, date: str | None = None) -> JournalDayOut:
    """Journal day view.

    For days with strangle activity, `by_index`/`stats.realized_pnl` are derived
    from the same entry→exit ledger as `/strangle/trades` (task 4.3) — realized
    P&L for a day+strategy MUST match across both surfaces. Non-strangle fills
    still populate the legacy `trades` list.
    """
    query_date = parse_ist_date(date)
    day_data = _service(request).get_day(query_date.isoformat())

    strangle_ids = _running_strangle_ids(request)
    if strangle_ids:
        from pdp.strategy.trade_ledger import (
            compute_totals,
            group_by_index,
            pair_trades,
            read_day_events,
        )

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

    return JournalDayOut(**day_data)


@router.put(
    "/{date}/metadata",
    response_model=StatusOut,
    status_code=200,
    dependencies=[Depends(require_auth)],
    summary="Update journal metadata",
    description="Update the notes, tags, and screenshots for a given day.",
)
async def update_metadata(request: Request, date: str, body: JournalMetadata) -> StatusOut:
    await _service(request).update_metadata(date, body.notes, body.tags, body.screenshots)
    return StatusOut(status="ok")


@router.get("/stats", response_model=list[dict])
async def get_journal_stats(request: Request, date: str | None = None) -> list[dict]:
    return _service(request).get_stats(parse_ist_date(date).isoformat())


@router.get("/strategy/{strategy_id}", response_model=JournalStrategyStatsOut)
async def get_strategy_stats(request: Request, strategy_id: str, date: str | None = None) -> JournalStrategyStatsOut:
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

        query_date = parse_ist_date(date)
        events = read_day_events(strategy_id, query_date)
        rows = pair_trades(events)
        by_index = group_by_index(rows)
        totals = compute_totals(rows)
        return JournalStrategyStatsOut(
            date=query_date.isoformat(),
            strategy_id=strategy_id,
            by_index=by_index,
            totals=totals,
            trades=rows,
        )

    # Non-strangle: fall back to traditional fill-based stats
    day_data = _service(request).get_day(parse_ist_date(date).isoformat())
    trades = [t for t in day_data.get("trades", []) if t.get("strategy_id") == strategy_id]

    from pdp.journal.stats import compute_daily_stats

    return JournalStrategyStatsOut(
        date=day_data.get("date"),
        strategy_id=strategy_id,
        stats=compute_daily_stats(trades),
    )
