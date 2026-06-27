from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.alerts import service
from pdp.alerts.enums import AlertStatus
from pdp.alerts.schemas import AlertCreate, AlertOut, AlertUpdate
from pdp.db.session import get_db

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _get_user_id(request) -> str:
    # TODO: Extract from JWT token in Authorization header
    # For v1, use a placeholder user_id; actual JWT validation deferred to v2
    # In production, this would validate the token and extract user_id claim
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        # For development: allow header-less requests with placeholder ID
        log.warning("auth_missing", path=request.url.path)
        return "user_123"
    # TODO: Parse JWT and extract user_id claim
    return "user_123"


@router.post("", response_model=AlertOut, status_code=201)
async def create_alert(
    alert_data: AlertCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    """Create a new alert."""
    user_id = _get_user_id(request)
    log.info("create_alert", user_id=user_id, security_id=alert_data.security_id)
    alert = await service.create_alert(db, user_id, alert_data)
    await db.commit()
    return AlertOut.model_validate(alert)


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    request: Request,
    status: AlertStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[AlertOut]:
    """List user's alerts."""
    user_id = _get_user_id(request)
    log.info("list_alerts", user_id=user_id, status=status)
    alerts = await service.list_alerts(db, user_id, status)
    return [AlertOut.model_validate(a) for a in alerts]


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(
    alert_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    """Get a specific alert."""
    user_id = _get_user_id(request)
    alert = await service.get_alert(db, user_id, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    return AlertOut.model_validate(alert)


@router.patch("/{alert_id}", response_model=AlertOut)
async def update_alert(
    alert_id: int,
    alert_data: AlertUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AlertOut:
    """Update an alert."""
    user_id = _get_user_id(request)
    log.info("update_alert", user_id=user_id, alert_id=alert_id)
    alert = await service.update_alert(db, user_id, alert_id, alert_data)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    await db.commit()
    return AlertOut.model_validate(alert)


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an alert."""
    user_id = _get_user_id(request)
    log.info("delete_alert", user_id=user_id, alert_id=alert_id)
    success = await service.delete_alert(db, user_id, alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="alert not found")
    await db.commit()
