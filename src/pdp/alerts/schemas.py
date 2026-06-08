from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from pdp.alerts.enums import AlertChannel, AlertCondition, AlertStatus


class AlertCreate(BaseModel):
    security_id: str
    condition: AlertCondition
    threshold: Decimal
    channels: list[AlertChannel] = [AlertChannel.WS]

    @field_validator("channels")
    @classmethod
    def channels_not_empty(cls, v: list[AlertChannel]) -> list[AlertChannel]:
        if not v:
            raise ValueError("channels cannot be empty")
        return v


class AlertUpdate(BaseModel):
    threshold: Decimal | None = None
    channels: list[AlertChannel] | None = None

    @field_validator("channels")
    @classmethod
    def channels_not_empty(cls, v: list[AlertChannel] | None) -> list[AlertChannel] | None:
        if v is not None and not v:
            raise ValueError("channels cannot be empty")
        return v


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    security_id: str
    condition: AlertCondition
    threshold: Decimal
    channels: list[str]
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
