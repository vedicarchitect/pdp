"""Risk REST endpoints: kill-switch, daily loss, and risk settings."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db, get_session_maker
from pdp.risk.service import KillSwitchService, compute_daily_loss
from pdp.settings import get_settings

log = structlog.get_logger()

risk_router = APIRouter(prefix="/api/v1/risk", tags=["risk"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_kill_switch = KillSwitchService()


@risk_router.post("/kill")
async def kill_switch(request: Request) -> JSONResponse:
    """Cancel all open orders and flatten all intraday (MIS/INTRADAY) positions atomically."""
    client_host = request.client.host if request.client else "unknown"
    requester = {"ip": client_host, "ts": datetime.now(UTC).isoformat()}

    order_router = request.app.state.order_router
    result = await _kill_switch.execute(get_session_maker(), order_router, requester)
    status_code = 200 if result["status"] == "ok" else 207
    return JSONResponse(content=result, status_code=status_code)


@risk_router.get("/daily-loss")
async def get_daily_loss(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Return today's realized + unrealized P&L and per-strategy breakdown."""
    portfolio_service = getattr(request.app.state, "portfolio_service", None)
    day_start_pnl = getattr(portfolio_service, "_day_start_pnl", 0)
    from decimal import Decimal
    data = await compute_daily_loss(db, Decimal(str(day_start_pnl)))
    return JSONResponse(content=data)


@settings_router.get("/risk")
async def get_risk_settings() -> JSONResponse:
    """Return configured risk cap values."""
    s = get_settings()
    return JSONResponse({
        "RISK_DAILY_LOSS_CAP_INR": s.RISK_DAILY_LOSS_CAP_INR,
        "RISK_PER_STRATEGY_LOSS_CAP_INR": s.RISK_PER_STRATEGY_LOSS_CAP_INR,
        "RISK_SOFT_CAP_PCT": s.RISK_SOFT_CAP_PCT,
        "hard_cap_pct": 100.0,
        "strategy_hard_cap_pct": 150.0,
    })
