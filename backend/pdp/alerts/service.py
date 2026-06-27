from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.alerts.enums import AlertStatus
from pdp.alerts.models import AlertRecord
from pdp.alerts.schemas import AlertCreate, AlertUpdate


async def create_alert(
    db: AsyncSession, user_id: str, alert_data: AlertCreate
) -> AlertRecord:
    channels = [c.value for c in alert_data.channels]
    alert = AlertRecord(
        user_id=user_id,
        security_id=alert_data.security_id,
        condition=alert_data.condition.value,
        threshold=alert_data.threshold,
        channels=channels,
        status=AlertStatus.ARMED.value,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    return alert


async def get_alert(db: AsyncSession, user_id: str, alert_id: int) -> AlertRecord | None:
    stmt = select(AlertRecord).where(
        AlertRecord.id == alert_id, AlertRecord.user_id == user_id
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_alerts(
    db: AsyncSession, user_id: str, status: AlertStatus | None = None
) -> list[AlertRecord]:
    stmt = select(AlertRecord).where(AlertRecord.user_id == user_id)
    if status:
        stmt = stmt.where(AlertRecord.status == status.value)
    result = await db.execute(stmt)
    return result.scalars().all()


async def update_alert(
    db: AsyncSession, user_id: str, alert_id: int, alert_data: AlertUpdate
) -> AlertRecord | None:
    alert = await get_alert(db, user_id, alert_id)
    if not alert:
        return None

    if alert_data.threshold is not None:
        alert.threshold = alert_data.threshold
    if alert_data.channels is not None:
        alert.channels = [c.value for c in alert_data.channels]

    await db.flush()
    await db.refresh(alert)
    return alert


async def delete_alert(db: AsyncSession, user_id: str, alert_id: int) -> bool:
    alert = await get_alert(db, user_id, alert_id)
    if not alert:
        return False

    await db.delete(alert)
    await db.flush()
    return True


async def get_alerts_by_security(db: AsyncSession, security_id: str) -> list[AlertRecord]:
    stmt = select(AlertRecord).where(
        AlertRecord.security_id == security_id,
        AlertRecord.status.in_([AlertStatus.ARMED.value, AlertStatus.TRIGGERED.value])
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def update_alert_status(
    db: AsyncSession, alert_id: int, status: AlertStatus
) -> AlertRecord | None:
    stmt = select(AlertRecord).where(AlertRecord.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalars().first()
    if alert:
        alert.status = status.value
        await db.flush()
        await db.refresh(alert)
    return alert
