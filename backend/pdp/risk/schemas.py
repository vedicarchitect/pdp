from pydantic import BaseModel
from typing import Any

class CancelledOrder(BaseModel):
    id: int
    security_id: str
    strategy_id: str | None = None

class FlattenedPosition(BaseModel):
    security_id: str
    exchange_segment: str
    product: str
    qty_flattened: int
    side: str

class KillSwitchResultOut(BaseModel):
    status: str
    cancelled_orders: list[CancelledOrder]
    flattened_positions: list[FlattenedPosition]
    errors: list[str]
    executed_at: str
    requester: dict[str, Any]

class DailyLossOut(BaseModel):
    total_realized_pnl: float
    total_unrealized_pnl: float
    day_pnl: float
    realized_loss_today: float
    per_strategy_realized_pnl: dict[str, float]

class RiskSettingsOut(BaseModel):
    RISK_DAILY_LOSS_CAP_INR: float
    RISK_PER_STRATEGY_LOSS_CAP_INR: float
    RISK_SOFT_CAP_PCT: float
    hard_cap_pct: float
    strategy_hard_cap_pct: float
