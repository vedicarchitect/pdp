from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict

import msgspec


class StrangleLeg(msgspec.Struct):
    security_id: str
    opt_type: str
    strike: float
    lots: int
    entry_price: float
    ltp: float | None
    mtm: float | None
    is_hedge: bool
    is_momentum: bool


class StrangleState(msgspec.Struct):
    mode: str
    strategy_id: str
    bucket: str | None
    score: float
    day_realized: float
    day_unrealized: float
    day_pnl: float
    done_for_day: bool
    vix_now: float | None
    n_open_legs: int
    n_open_shorts: int
    n_open_hedges: int
    n_open_momentum: int
    started_at: str | None


class StrangleActivityEvent(msgspec.Struct, omit_defaults=True):
    event_type: str
    strategy_id: str
    account_id: str
    ist_time: str
    snapshot_date: str | None = None
    underlying: str | None = None
    spot: float | None = None
    score: float | None = None
    bucket: str | None = None


class WatchlistEntryOut(msgspec.Struct):
    security_id: str
    exchange_segment: str
    timeframes: list[str]


class StrategyInfo(msgspec.Struct):
    id: str
    status: str
    dropped_ticks: int
    watchlist: list[WatchlistEntryOut]


def strategy_info_from_dict(d: dict[str, Any]) -> StrategyInfo:
    watchlist = [
        WatchlistEntryOut(
            security_id=w["security_id"],
            exchange_segment=w["exchange_segment"],
            timeframes=w["timeframes"],
        )
        for w in d.get("watchlist", [])
    ]
    return StrategyInfo(
        id=d["id"],
        status=str(d["status"]),
        dropped_ticks=d.get("dropped_ticks", 0),
        watchlist=watchlist,
    )


class StrategyListOut(BaseModel):
    strategies: list[dict[str, Any]]

class StrategyRegisterOut(BaseModel):
    id: str
    kind: str
    underlying: str
    source: str
    params_schema: list[dict[str, Any]]
    defaults: dict[str, Any]

class StrategyActionOut(BaseModel):
    id: str
    status: str
    dropped_ticks: int | None = None
    watchlist: list[dict[str, Any]] | None = None

class StrangleStatusOut(BaseModel):
    model_config = ConfigDict(extra="allow")

class StrangleLegsOut(BaseModel):
    legs: list[dict[str, Any]]

class StrangleActivityOut(BaseModel):
    events: list[dict[str, Any]]
    total: int

class StrangleStatsOut(BaseModel):
    day_realized: float
    day_unrealized: float
    day_pnl: float
    trade_count: int
    open_pe_lots: int
    open_ce_lots: int
    open_hedge_lots: int

class StranglePnlOut(BaseModel):
    by_index: list[dict[str, Any]]
    totals: dict[str, Any]

class StrangleTradesOut(BaseModel):
    date: str
    by_index: dict[str, Any]
    totals: dict[str, Any]

class StrangleMonitorOut(BaseModel):
    indices: dict[str, dict[str, Any]]
    groups: list[dict[str, Any]]
    totals: dict[str, float]
    status: dict[str, Any]
    recent_events: list[dict[str, Any]]
    indicators: dict[str, Any]

class StrangleReadinessOut(BaseModel):
    state: str
    components: list[dict[str, Any]]

class LevelsResponseOut(BaseModel):
    model_config = ConfigDict(extra="allow")
