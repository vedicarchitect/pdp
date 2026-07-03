"""Portfolio REST endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.broker_sync.models import BrokerFund, BrokerHolding
from pdp.db.session import get_db
from pdp.orders.models import Position
from pdp.portfolio.sector_map import sector_for

log = structlog.get_logger()

_CONCENTRATION_WARN_PCT = 40.0
_CASH_DRAG_WARN_PCT = 20.0
_MOCK_ADVISORY = {
    "is_mock": True,
    "holdings": [
        {"sector": "Technology", "percentage": 45.0, "value": 45000.0},
        {"sector": "Financials", "percentage": 25.0, "value": 25000.0},
        {"sector": "Healthcare", "percentage": 15.0, "value": 15000.0},
        {"sector": "Cash", "percentage": 15.0, "value": 15000.0},
    ],
    "advice": [
        {
            "id": "a1",
            "title": "Reduce Tech Exposure",
            "description": "Technology sector exceeds 40% of portfolio. Consider rebalancing.",
            "action": "Sell Tech",
            "severity": "high",
        },
        {
            "id": "a2",
            "title": "Deploy Cash",
            "description": "Cash drag is present. Consider investing in undervalued Healthcare equities.",
            "action": "Buy Healthcare",
            "severity": "medium",
        },
    ],
}

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


def _pos_dict(p: Position) -> dict:
    return {
        "security_id": p.security_id,
        "exchange_segment": p.exchange_segment,
        "product": p.product,
        "net_qty": p.net_qty,
        "avg_price": str(p.avg_price),
        "realized_pnl": str(p.realized_pnl),
        "unrealized_pnl": str(p.unrealized_pnl),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/positions")
async def get_positions(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    result = await db.execute(select(Position))
    positions = result.scalars().all()
    dicts = [_pos_dict(p) for p in positions]
    return JSONResponse({"positions": dicts, "count": len(dicts)})


@router.get("/summary")
async def get_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    from pdp.settings import get_settings

    result = await db.execute(select(Position))
    positions = result.scalars().all()

    total_unrealized = sum((p.unrealized_pnl or Decimal("0")) for p in positions)
    total_realized = sum((p.realized_pnl or Decimal("0")) for p in positions)
    open_count = sum(1 for p in positions if p.net_qty != 0)

    settings = get_settings()
    mode = "live" if settings.LIVE else "paper"

    return JSONResponse(
        {
            "total_unrealized_pnl": float(total_unrealized),
            "total_realized_pnl": float(total_realized),
            "day_pnl": float(total_unrealized + total_realized),
            "open_positions": open_count,
            "mode": mode,
        }
    )


@router.get("/advisory")
async def get_advisory(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    holdings = (await db.execute(select(BrokerHolding))).scalars().all()
    if not holdings:
        # No broker sync has run yet (see pdp/broker_sync) — fall back to demo data
        # so the screen still renders something meaningful.
        return JSONResponse(content=_MOCK_ADVISORY)

    funds = (await db.execute(select(BrokerFund))).scalars().all()

    sector_values: dict[str, float] = {}
    total_value = 0.0
    for h in holdings:
        price = h.last_price if h.last_price is not None else h.avg_cost_price
        value = float(h.total_qty) * float(price)
        sector = sector_for(h.symbol)
        sector_values[sector] = sector_values.get(sector, 0.0) + value
        total_value += value

    cash_available = float(sum((f.available_balance for f in funds), Decimal("0")))
    if cash_available > 0:
        sector_values["Cash"] = sector_values.get("Cash", 0.0) + cash_available
        total_value += cash_available

    holdings_out = [
        {
            "sector": sector,
            "percentage": round((value / total_value) * 100, 2) if total_value else 0.0,
            "value": round(value, 2),
        }
        for sector, value in sorted(sector_values.items(), key=lambda kv: -kv[1])
    ]

    advice: list[dict[str, Any]] = []
    for sector, value in sector_values.items():
        if sector == "Cash" or not total_value:
            continue
        pct = (value / total_value) * 100
        if pct > _CONCENTRATION_WARN_PCT:
            advice.append(
                {
                    "id": f"concentration-{sector.lower()}",
                    "title": f"Reduce {sector} Exposure",
                    "description": (
                        f"{sector} sector is {pct:.1f}% of the portfolio, above the "
                        f"{_CONCENTRATION_WARN_PCT:.0f}% concentration guideline. Consider rebalancing."
                    ),
                    "action": f"Review {sector}",
                    "severity": "high",
                }
            )

    cash_pct = (sector_values.get("Cash", 0.0) / total_value * 100) if total_value else 0.0
    if cash_pct > _CASH_DRAG_WARN_PCT:
        advice.append(
            {
                "id": "cash-drag",
                "title": "Deploy Cash",
                "description": (
                    f"Cash is {cash_pct:.1f}% of the portfolio. Consider deploying idle "
                    "funds into undervalued holdings."
                ),
                "action": "Screen ideas",
                "severity": "medium",
            }
        )

    data = {"is_mock": False, "holdings": holdings_out, "advice": advice}

    mongo_db = getattr(request.app.state, "mongo_db", None)
    if mongo_db is not None:
        try:
            await mongo_db["advisory_snapshots"].insert_one(
                {"snapshot_ts": datetime.now(UTC), **data}
            )
        except Exception as exc:
            log.warning("advisory_snapshot_write_failed", exc=str(exc))

    return JSONResponse(content=data)


_MOCK_HOLDINGS = {
    "is_mock": True,
    "summary": {
        "total_invested": 82000.0,
        "total_current_value": 100000.0,
        "total_pnl": 18000.0,
        "total_pnl_pct": 21.95,
        "holdings_count": 3,
        "cash_available": 15000.0,
    },
    "holdings": [
        {
            "symbol": "TCS", "exchange": "NSE", "sector": "Technology",
            "qty": 20, "avg_price": 3200.0, "last_price": 3800.0,
            "invested_value": 64000.0, "current_value": 76000.0,
            "pnl": 12000.0, "pnl_pct": 18.75,
        },
        {
            "symbol": "HDFCBANK", "exchange": "NSE", "sector": "Financials",
            "qty": 10, "avg_price": 1400.0, "last_price": 1650.0,
            "invested_value": 14000.0, "current_value": 16500.0,
            "pnl": 2500.0, "pnl_pct": 17.86,
        },
        {
            "symbol": "SUNPHARMA", "exchange": "NSE", "sector": "Healthcare",
            "qty": 5, "avg_price": 800.0, "last_price": 1100.0,
            "invested_value": 4000.0, "current_value": 5500.0,
            "pnl": 1500.0, "pnl_pct": 37.5,
        },
    ],
}


@router.get("/holdings")
async def get_holdings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    holdings = (await db.execute(select(BrokerHolding))).scalars().all()
    if not holdings:
        return JSONResponse(content=_MOCK_HOLDINGS)

    funds = (await db.execute(select(BrokerFund))).scalars().all()
    cash_available = float(sum((f.available_balance for f in funds), Decimal("0")))

    rows: list[dict[str, Any]] = []
    total_invested = 0.0
    total_current = 0.0
    for h in holdings:
        last_price = h.last_price if h.last_price is not None else h.avg_cost_price
        invested_value = float(h.total_qty) * float(h.avg_cost_price)
        current_value = float(h.total_qty) * float(last_price)
        pnl = current_value - invested_value
        pnl_pct = (pnl / invested_value * 100) if invested_value else 0.0
        total_invested += invested_value
        total_current += current_value
        rows.append(
            {
                "symbol": h.symbol or h.security_id,
                "exchange": h.exchange or "",
                "sector": sector_for(h.symbol),
                "qty": h.total_qty,
                "avg_price": float(h.avg_cost_price),
                "last_price": float(last_price),
                "invested_value": round(invested_value, 2),
                "current_value": round(current_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
        )

    rows.sort(key=lambda r: -r["current_value"])
    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0

    return JSONResponse(
        content={
            "is_mock": False,
            "summary": {
                "total_invested": round(total_invested, 2),
                "total_current_value": round(total_current, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "holdings_count": len(rows),
                "cash_available": round(cash_available, 2),
            },
            "holdings": rows,
        }
    )


@router.get("/history")
async def get_history(request: Request) -> JSONResponse:
    mongo_db = getattr(request.app.state, "mongo_db", None)
    history: list[dict[str, Any]] = []

    if mongo_db is not None:
        try:
            cursor = mongo_db["paper_journal"].find({}, {"date": 1, "stats.realized_pnl": 1}).sort(
                "date", 1
            )
            docs = await cursor.to_list(length=None)
        except Exception as exc:
            log.warning("advisory_history_read_failed", exc=str(exc))
            docs = []

        docs = docs[-30:]
        cumulative = 0.0
        for doc in docs:
            pnl = float(doc.get("stats", {}).get("realized_pnl", 0.0) or 0.0)
            cumulative += pnl
            history.append(
                {
                    "date": doc["date"],
                    "pnl": round(cumulative, 2),
                    "value": round(cumulative, 2),
                }
            )

    return JSONResponse(content={"history": history, "is_mock": not history})
