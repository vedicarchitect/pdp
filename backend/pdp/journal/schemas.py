from pydantic import BaseModel
from typing import Any

class JournalDayOut(BaseModel):
    date: str | None = None
    stats: dict[str, Any] | None = None
    trades: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    by_index: dict[str, Any] | None = None
    totals: dict[str, Any] | None = None

class StatusOut(BaseModel):
    status: str

class JournalStrategyStatsOut(BaseModel):
    date: str | None = None
    strategy_id: str
    stats: dict[str, Any] | None = None
    by_index: dict[str, Any] | None = None
    totals: dict[str, Any] | None = None
    trades: list[dict[str, Any]] | None = None
