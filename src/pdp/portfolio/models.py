from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class PositionState:
    strategy_id: str | None
    security_id: str
    exchange_segment: str
    product: str
    net_qty: int
    avg_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    updated_at: datetime
    ltp_stale: bool = field(default=False)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "security_id": self.security_id,
            "exchange_segment": self.exchange_segment,
            "product": self.product,
            "net_qty": self.net_qty,
            "avg_price": str(self.avg_price),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "updated_at": self.updated_at.isoformat(),
            "ltp_stale": self.ltp_stale,
        }
