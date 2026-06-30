from __future__ import annotations

import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/news")
async def get_news() -> JSONResponse:
    # Mock news data
    data = {
        "articles": [
            {
                "id": "n1",
                "headline": "Fed signals potential rate cuts later this year",
                "source": "Reuters",
                "url": "https://example.com/news1",
                "published_at": datetime.datetime.now().isoformat(),
                "sentiment": "positive",
            },
            {
                "id": "n2",
                "headline": "Tech stocks rally as AI demand surges",
                "source": "Bloomberg",
                "url": "https://example.com/news2",
                "published_at": (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat(),
                "sentiment": "positive",
            },
            {
                "id": "n3",
                "headline": "Oil prices dip amid global growth concerns",
                "source": "WSJ",
                "url": "https://example.com/news3",
                "published_at": (datetime.datetime.now() - datetime.timedelta(hours=5)).isoformat(),
                "sentiment": "negative",
            },
        ]
    }
    return JSONResponse(content=data)

@router.get("/sentiment")
async def get_sentiment() -> JSONResponse:
    # Mock X/Twitter sentiment scores
    data = {
        "overall_score": 68,
        "label": "Bullish",
        "breakdown": {
            "positive": 55,
            "neutral": 30,
            "negative": 15,
        }
    }
    return JSONResponse(content=data)

@router.get("/commodities")
async def get_commodities() -> JSONResponse:
    # Mock commodity prices
    data = {
        "commodities": [
            {"symbol": "GOLD", "name": "Gold", "price": 2350.40, "change_pct": 0.8},
            {"symbol": "SILVER", "name": "Silver", "price": 28.15, "change_pct": 1.2},
            {"symbol": "CRUDE", "name": "Crude Oil", "price": 78.50, "change_pct": -0.5},
            {"symbol": "NATGAS", "name": "Natural Gas", "price": 2.65, "change_pct": -1.1},
        ]
    }
    return JSONResponse(content=data)

@router.get("/calendar")
async def get_calendar() -> JSONResponse:
    # Mock economic calendar
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
