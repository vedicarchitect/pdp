from __future__ import annotations

import msgspec
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from pdp.strategy.host import AlreadyRunning, NotRunning, StrategyHost
from pdp.strategy.schemas import strategy_info_from_dict

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
strangle_router = APIRouter(prefix="/api/v1/strangle", tags=["strangle"])


def _host(request: Request) -> StrategyHost:
    return request.app.state.strategy_host


@router.get("")
async def list_strategies(request: Request) -> JSONResponse:
    host = _host(request)
    items = [strategy_info_from_dict(d) for d in host.list_all()]
    import msgspec
    return JSONResponse(content=msgspec.to_builtins(items))


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str, request: Request) -> JSONResponse:
    host = _host(request)
    try:
        await host.start(strategy_id)
    except AlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ImportError, FileNotFoundError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    items = [d for d in host.list_all() if d["id"] == strategy_id]
    if items:
        info = strategy_info_from_dict(items[0])
        return JSONResponse(content=msgspec.to_builtins(info))
    return JSONResponse(content={"id": strategy_id, "status": "RUNNING"})


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str, request: Request) -> JSONResponse:
    host = _host(request)
    try:
        await host.stop(strategy_id)
    except NotRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return JSONResponse(content={"id": strategy_id, "status": "STOPPED"})


# ------------------------------------------------------------------ #
# Strangle execution console — read-only API                          #
# ------------------------------------------------------------------ #

def _get_strangle(request: Request, strategy_id: str | None = None):
    from pdp.strategies.directional_strangle import DirectionalStrangle
    host: StrategyHost = request.app.state.strategy_host
    for sid, state in host._running.items():
        if isinstance(state.instance, DirectionalStrangle):
            if strategy_id is None or sid == strategy_id:
                return state.instance
    detail = (
        f"DirectionalStrangle '{strategy_id}' not running"
        if strategy_id else "DirectionalStrangle not running"
    )
    raise HTTPException(status_code=404, detail=detail)


@strangle_router.get("/status")
async def strangle_status(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return JSONResponse(content=data)


@strangle_router.get("/legs")
async def strangle_legs(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return JSONResponse(content={"legs": data["legs"]})


@strangle_router.get("/activity")
async def strangle_activity(
    request: Request,
    n: int = Query(default=50, ge=1, le=200),
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    events = list(strategy._activity)
    events.reverse()       # newest-first
    return JSONResponse(content={"events": events[:n], "total": len(events)})


@strangle_router.get("/stats")
async def strangle_stats(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    open_pe_lots = sum(lg["lots"] for lg in data["legs"]
                       if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "PE")
    open_ce_lots = sum(lg["lots"] for lg in data["legs"]
                       if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "CE")
    open_hedge_lots = sum(lg["lots"] for lg in data["legs"] if lg["is_hedge"])
    trade_count = sum(1 for e in strategy._activity if e.get("event_type") in ("leg_close", "take_profit"))
    return JSONResponse(content={
        "day_realized": data["day_realized"],
        "day_unrealized": data["day_unrealized"],
        "day_pnl": data["day_pnl"],
        "trade_count": trade_count,
        "open_pe_lots": open_pe_lots,
        "open_ce_lots": open_ce_lots,
        "open_hedge_lots": open_hedge_lots,
    })
