from pydantic import BaseModel
from typing import Any
from datetime import datetime

class PositionOut(BaseModel):
    id: int | None = None
    strategy_id: str | None = None
    security_id: str
    exchange_segment: str
    product: str
    net_qty: int
    avg_price: str
    realized_pnl: str
    unrealized_pnl: str
    updated_at: datetime | None = None

class SummaryOut(BaseModel):
    total_unrealized_pnl: float
    total_realized_pnl: float
    day_pnl: float
    open_positions: int
    mode: str

class AdvisoryOut(BaseModel):
    is_mock: bool
    holdings: list[dict[str, Any]]
    advice: list[dict[str, Any]]

class HoldingsOut(BaseModel):
    is_mock: bool
    summary: dict[str, Any]
    holdings: list[dict[str, Any]]

class HistoryOut(BaseModel):
    history: list[dict[str, Any]]
    is_mock: bool
