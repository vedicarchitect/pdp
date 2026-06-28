from __future__ import annotations

from typing import Any

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
