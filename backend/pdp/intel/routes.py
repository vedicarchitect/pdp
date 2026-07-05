from __future__ import annotations

import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pdp.intel.sections import (
    compute_commodities,
    compute_global_indices,
    compute_news,
    compute_next_expiry,
    compute_sentiment,
    compute_vix,
)

router = APIRouter()


@router.get("/global-indices")
async def get_global_indices(request: Request) -> JSONResponse:
    return JSONResponse(await compute_global_indices(request))


@router.get("/news")
async def get_news(request: Request) -> JSONResponse:
    return JSONResponse(await compute_news(request))


@router.get("/sentiment")
async def get_sentiment(request: Request) -> JSONResponse:
    return JSONResponse(await compute_sentiment(request))


@router.get("/commodities")
async def get_commodities(request: Request) -> JSONResponse:
    """MCX commodity LTP in INR — from the live Dhan feed's Redis ltp cache, not a
    third-party library."""
    return JSONResponse({"commodities": await compute_commodities(request)})


@router.get("/vix")
async def get_vix(request: Request) -> JSONResponse:
    return JSONResponse(await compute_vix(request))


@router.get("/next-expiry")
async def get_next_expiry(request: Request) -> JSONResponse:
    return JSONResponse(await compute_next_expiry())


@router.get("/calendar")
async def get_calendar() -> JSONResponse:
    # Mock economic calendar — out of scope for flutter-dashboard; unchanged.
    data = {
        "events": [
            {
                "id": "e1",
                "event": "Core CPI (MoM) (May)",
                "country": "US",
                "impact": "High",
                "time": (datetime.datetime.now() + datetime.timedelta(hours=2)).isoformat(),
                "actual": None,
                "forecast": "0.3%",
                "previous": "0.3%",
            },
            {
                "id": "e2",
                "event": "Fed Interest Rate Decision",
                "country": "US",
                "impact": "High",
                "time": (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat(),
                "actual": None,
                "forecast": "5.50%",
                "previous": "5.50%",
            },
            {
                "id": "e3",
                "event": "Initial Jobless Claims",
                "country": "US",
                "impact": "Medium",
                "time": (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat(),
                "actual": None,
                "forecast": "215K",
                "previous": "219K",
            },
        ]
    }
    return JSONResponse(content=data)
