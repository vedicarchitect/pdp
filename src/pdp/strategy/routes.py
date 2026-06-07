from __future__ import annotations

import msgspec
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from pdp.strategy.host import AlreadyRunning, NotRunning, StrategyHost
from pdp.strategy.schemas import strategy_info_from_dict

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


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
