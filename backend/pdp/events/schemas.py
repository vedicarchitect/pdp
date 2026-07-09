from pydantic import BaseModel
from typing import Any

class EventOut(BaseModel):
    id: str | None = None
    ts: str | None = None
    event_type: str | None = None
    severity: str | None = None
    security_id: str | None = None
    message: str | None = None
    data: dict[str, Any] | None = None

class EventConfigOut(BaseModel):
    enabled: bool
    timeframes: list[str] | None = None
    ema_pairs: list[list[int]] | None = None
    watch_levels: dict[str, Any] | None = None
    otm_distance_pts: int | None = None
    mtm_swing_inr: float | None = None
    push_enabled: bool | None = None
    push_min_severity: str | None = None
    event_type_push: dict[str, bool]

class EventTypeConfigPatchResponse(BaseModel):
    event_type: str
    push_enabled: bool

class VapidKeyOut(BaseModel):
    public_key: str

class StatusOut(BaseModel):
    status: str
