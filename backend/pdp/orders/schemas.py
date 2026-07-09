from pydantic import BaseModel
from typing import Literal
from datetime import datetime

class OrderOut(BaseModel):
    id: int
    client_order_id: str | None = None
    broker: str
    mode: str
    security_id: str
    exchange_segment: str
    side: str
    qty: int
    order_type: str
    price: str | None = None
    trigger_price: str | None = None
    product: str
    status: str
    placed_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    reject_reason: str | None = None
    strategy_id: str | None = None

class TradeOut(BaseModel):
    id: int
    order_id: int
    security_id: str
    exchange_segment: str
    side: str
    qty: int
    fill_price: str
    slippage_bps: str
    charges: str
    filled_at: datetime

class PositionOut(BaseModel):
    id: int
    strategy_id: str | None = None
    security_id: str
    exchange_segment: str
    product: str
    net_qty: int
    avg_price: str
    realized_pnl: str
    unrealized_pnl: str
    updated_at: datetime | None = None
