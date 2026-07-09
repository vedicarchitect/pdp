from pydantic import BaseModel
from typing import Any

class BacktestRunListOut(BaseModel):
    id: int
    strategy_id: str
    from_date: str
    to_date: str
    start_equity: float
    end_equity: float
    total_trades: int
    created_at: str

class BacktestRunDetailOut(BaseModel):
    id: int
    strategy_id: str
    from_date: str
    to_date: str
    start_equity: float
    end_equity: float
    total_return_pct: float
    total_trades: int
    config: dict[str, Any] | None = None
    created_at: str

class BacktestTradeOut(BaseModel):
    id: int
    symbol: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_timestamp: str
    exit_timestamp: str
    realized_pnl: float

class BacktestDailyOut(BaseModel):
    date: str
    starting_equity: float
    ending_equity: float
    daily_pnl: float
    trades_count: int
    max_drawdown: float
    current_drawdown_pct: float

class BacktestDailyResponse(BaseModel):
    run_id: int
    daily_count: int
    daily: list[BacktestDailyOut]

class BacktestResultOut(BaseModel):
    config_name: str
    date_range: dict[str, str]
    summary: dict[str, float | int]
    equity_curve: list[float]
    daily_pnl: dict[str, float]
    weekday_stats: dict[str, float]
    trade_log: list[dict[str, Any]]
