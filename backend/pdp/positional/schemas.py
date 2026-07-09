from pydantic import BaseModel
from datetime import datetime

class PositionalSnapshotOut(BaseModel):
    date: str
    total_unrealized_pnl: float
    total_realized_pnl: float
    day_pnl: float
    position_count: int
    created_at: datetime
    mode: str
