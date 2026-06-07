from __future__ import annotations

from typing import Any

import msgspec


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
