from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


def _service(request: Request):
    return request.app.state.journal_service


@router.get("")
async def get_journal(request: Request, date: str | None = None) -> JSONResponse:
    return JSONResponse(content=_service(request).get_day(date))


@router.get("/stats")
async def get_journal_stats(request: Request, date: str | None = None) -> JSONResponse:
    return JSONResponse(content=_service(request).get_stats(date))
