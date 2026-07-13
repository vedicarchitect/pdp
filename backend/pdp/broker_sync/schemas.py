from pydantic import BaseModel
from typing import Any
from datetime import datetime

class BrokerSyncRunOut(BaseModel):
    """Mirrors the keys produced by ``service._run_dict``."""

    id: str
    account_id: str
    snapshot_date: str
    trigger: str
    status: str
    counts: dict[str, int] = {}
    recon: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class BrokerSyncStatusOut(BaseModel):
    """Lets a client tell apart: disabled, no credentials, never run, empty account."""

    enabled: bool
    has_credentials: bool
    live_mode: bool
    # Mirror freshness. The intraday refresh writes no run row, so this — not `last_run` —
    # is what distinguishes "never synced" from "synced, account is flat".
    last_state_refresh_at: str | None = None
    last_run: BrokerSyncRunOut | None = None

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
