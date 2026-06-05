from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True)
class Tick:
    security_id: str
    exchange_segment: str
    ltp: Decimal
    ltt: datetime
    volume: int = 0
    oi: int = 0
    ts_recv: float = field(default_factory=lambda: __import__("time").monotonic())
