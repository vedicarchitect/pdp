from pydantic import BaseModel
from typing import Any

class SubscriptionActionOut(BaseModel):
    status: str
    security_id: str
    exchange_segment: str | None = None

class BarOut(BaseModel):
    security_id: str
    timeframe: str
    bar_time: str
    open: str
    high: str
    low: str
    close: str
    volume: int
    oi: int

class SubscriptionOut(BaseModel):
    security_id: str
    exchange_segment: str
