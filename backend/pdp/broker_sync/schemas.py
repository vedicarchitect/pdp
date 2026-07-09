from pydantic import BaseModel
from typing import Any
from datetime import datetime

class BrokerSyncRunOut(BaseModel):
    id: str
    sync_date: str | None = None
    status: str
    trigger: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    summary: dict[str, Any] | None = None

class BrokerHoldingOut(BaseModel):
    account_id: str
    security_id: str
    isin: str | None = None
    symbol: str | None = None
    exchange: str | None = None
    total_qty: int
    available_qty: int
    avg_cost_price: str
    last_price: str | None = None
    last_synced_at: str | None = None

class BrokerPositionOut(BaseModel):
    account_id: str
    security_id: str
    exchange_segment: str
    product_type: str
    symbol: str | None = None
    net_qty: int
    buy_avg: str
    sell_avg: str
    realized_pnl: str
    unrealized_pnl: str
    last_synced_at: str | None = None

class BrokerFundOut(BaseModel):
    account_id: str
    available_balance: str
    utilized_amount: str
    collateral_amount: str
    withdrawable_balance: str
    last_synced_at: str | None = None
