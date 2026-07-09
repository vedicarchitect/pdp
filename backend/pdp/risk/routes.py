"""Risk REST endpoints: kill-switch, daily loss, and risk settings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.db.session import get_db, get_session_maker
from pdp.deps import require_auth
from pdp.risk.service import KillSwitchService, compute_daily_loss
from pdp.settings import get_settings
from pdp.risk.schemas import KillSwitchResultOut, DailyLossOut, RiskSettingsOut

log = structlog.get_logger()

risk_router = APIRouter(prefix="/api/v1/risk", tags=["risk"])
settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_kill_switch = KillSwitchService()


@risk_router.post(
    "/kill",
    response_model=KillSwitchResultOut,
    status_code=200,
    dependencies=[Depends(require_auth)],
    summary="Execute kill switch",
    description="Cancel all open orders and flatten all intraday (MIS/INTRADAY) positions atomically.",
)
async def kill_switch(request: Request, response: Response) -> KillSwitchResultOut:
    """Cancel all open orders and flatten all intraday (MIS/INTRADAY) positions atomically."""
    client_host = request.client.host if request.client else "unknown"
    requester = {"ip": client_host, "ts": datetime.now(UTC).isoformat()}

    order_router = getattr(request.app.state, "order_router", None)
    if order_router:
        result = await _kill_switch.execute(get_session_maker(), order_router, requester)
    else:
        import uuid
        from pdp.orders.command_channel import OrderCommand
        cmd = OrderCommand(
            cmd_id=str(uuid.uuid4()),
            kind="kill",
            requester="api",
            ts=datetime.now(UTC)
        )
        producer = request.app.state.command_producer
        res = await producer.execute(cmd)
        if res.status == "killed":
            result = {"status": "ok", "message": "Kill switch executed", "details": {}}
        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail=res.detail or "Engine rejected kill")

    status_code = 200 if result["status"] == "ok" else 207
    response.status_code = status_code
    return KillSwitchResultOut(**result)


@risk_router.get(
    "/daily-loss",
    response_model=DailyLossOut,
    summary="Get daily loss summary",
)
async def get_daily_loss(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyLossOut:
    """Return today's realized + unrealized P&L and per-strategy breakdown."""
    portfolio_service = getattr(request.app.state, "portfolio_service", None)
    day_start_pnl = getattr(portfolio_service, "_day_start_pnl", 0)
    from decimal import Decimal

    data = await compute_daily_loss(db, Decimal(str(day_start_pnl)))
    return DailyLossOut(**data)


@settings_router.get(
    "/risk",
    response_model=RiskSettingsOut,
    summary="Get risk settings",
)
async def get_risk_settings() -> RiskSettingsOut:
    """Return configured risk cap values."""
    s = get_settings()
    return RiskSettingsOut(
        RISK_DAILY_LOSS_CAP_INR=s.RISK_DAILY_LOSS_CAP_INR,
        RISK_PER_STRATEGY_LOSS_CAP_INR=s.RISK_PER_STRATEGY_LOSS_CAP_INR,
        RISK_SOFT_CAP_PCT=s.RISK_SOFT_CAP_PCT,
        hard_cap_pct=100.0,
        strategy_hard_cap_pct=150.0,
    )


@risk_router.post(
    "/positions/{security_id}/modify",
    response_model=dict,
    status_code=202,
    dependencies=[Depends(require_auth)],
    summary="Modify position risk limits",
)
async def modify_position_risk(security_id: str) -> dict:
    """SL/Target/Trailing SL modification — not yet implemented."""
    from fastapi import HTTPException

    raise HTTPException(
        status_code=501,
        detail="Position risk modification not yet implemented. Configure static risk caps in settings.",
    )
