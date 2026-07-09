from __future__ import annotations

import datetime

from fastapi import APIRouter, Request

from pdp.intel.sections import (
    compute_commodities,
    compute_global_indices,
    compute_news,
    compute_next_expiry,
    compute_sentiment,
    compute_vix,
)
from pdp.intel.schemas import (
    GlobalIndicesOut,
    NewsOut,
    SentimentOut,
    CommoditiesOut,
    VixOut,
    NextExpiryOut,
    CalendarOut,
)

router = APIRouter()


@router.get("/global-indices", response_model=GlobalIndicesOut)
async def get_global_indices(request: Request) -> GlobalIndicesOut:
    return GlobalIndicesOut(**await compute_global_indices(request))


@router.get("/news", response_model=NewsOut)
async def get_news(request: Request) -> NewsOut:
    return NewsOut(**await compute_news(request))


@router.get("/sentiment", response_model=SentimentOut)
async def get_sentiment(request: Request) -> SentimentOut:
    return SentimentOut(**await compute_sentiment(request))


@router.get("/commodities", response_model=CommoditiesOut)
async def get_commodities(request: Request) -> CommoditiesOut:
    """MCX commodity LTP in INR — from the live Dhan feed's Redis ltp cache, not a
    third-party library."""
    return CommoditiesOut(commodities=await compute_commodities(request))


@router.get("/vix", response_model=VixOut)
async def get_vix(request: Request) -> VixOut:
    return VixOut(**await compute_vix(request))


@router.get("/next-expiry", response_model=NextExpiryOut)
async def get_next_expiry(request: Request) -> NextExpiryOut:
    return NextExpiryOut(**await compute_next_expiry())


@router.get("/calendar", response_model=CalendarOut)
async def get_calendar() -> CalendarOut:
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
    return CalendarOut(**data)
