from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class PositionalSnapshotDocument(BaseModel):
    date: str  # YYYY-MM-DD
    total_unrealized_pnl: float
    total_realized_pnl: float
    day_pnl: float
    position_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: str = "paper"
