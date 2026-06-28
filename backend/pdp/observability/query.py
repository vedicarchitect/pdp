"""Read-side helpers: unified log search + bar-anchored strangle session narrative.

The session narrative replaces the old flat-file export — it is rebuilt on demand by
querying `pdp-strangle-events-*`. Each `bias_evaluated` event anchors a bar; subsequent
events attach to that bar as actions (or a `leg_status` snapshot) until the next anchor.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pdp.settings import get_settings

if TYPE_CHECKING:
    from opensearchpy import AsyncOpenSearch

_MAX_EVENTS = 5000


async def search_logs(
    client: AsyncOpenSearch,
    *,
    source: str | None = None,
    level: str | None = None,
    query: str | None = None,
    size: int = 100,
) -> list[dict[str, Any]]:
    """Search the universal `pdp-logs-*` index, optionally filtered by source/level/text."""
    prefix = get_settings().OPENSEARCH_INDEX_PREFIX
    must: list[dict[str, Any]] = []
    if source:
        must.append({"term": {"source": source}})
    if level:
        must.append({"term": {"level": level}})
    if query:
        must.append({"match": {"event": query}})
    body = {
        "size": size,
        "sort": [{"@timestamp": "desc"}],
        "query": {"bool": {"must": must}} if must else {"match_all": {}},
    }
    resp = await client.search(index=f"{prefix}-logs-*", body=body)
    return [h["_source"] for h in resp.get("hits", {}).get("hits", [])]


async def fetch_session_events(
    client: AsyncOpenSearch, *, date: str, strategy_id: str
) -> list[dict[str, Any]]:
    prefix = get_settings().OPENSEARCH_INDEX_PREFIX
    body = {
        "size": _MAX_EVENTS,
        "sort": [{"ist_time": "asc"}],
        "query": {
            "bool": {
                "must": [
                    {"term": {"snapshot_date": date}},
                    {"term": {"strategy_id": strategy_id}},
                ]
            }
        },
    }
    resp = await client.search(index=f"{prefix}-strangle-events-*", body=body)
    return [h["_source"] for h in resp.get("hits", {}).get("hits", [])]


def build_session(events: list[dict[str, Any]], *, date: str, strategy_id: str) -> dict[str, Any]:
    """Group a day's events into bar-anchored blocks + a summary (pure, testable)."""
    bars: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    counts = {"bias": 0, "opens": 0, "closes": 0, "stops": 0, "tps": 0, "rolls": 0}
    buckets_seen: list[str] = []
    day_pnl: float | None = None

    for ev in events:
        et = ev.get("event_type")
        if et == "bias_evaluated":
            counts["bias"] += 1
            bucket = ev.get("bucket")
            if bucket and bucket not in buckets_seen:
                buckets_seen.append(bucket)
            current = {
                "bar_time": ev.get("ist_time"),
                "bucket": bucket,
                "score": ev.get("score"),
                "spot": ev.get("spot"),
                "bias_votes": ev.get("bias_votes"),
                "leg_status": None,
                "actions": [],
            }
            bars.append(current)
            continue

        if et == "leg_status":
            if current is not None:
                current["leg_status"] = ev
            continue

        # any other action
        if et == "leg_open":
            counts["opens"] += 1
        elif et == "leg_close":
            counts["closes"] += 1
        elif et in ("stop_half", "stop_all"):
            counts["stops"] += 1
        elif et == "take_profit":
            counts["tps"] += 1
        elif et == "rolled":
            counts["rolls"] += 1
        if ev.get("day_pnl") is not None:
            day_pnl = ev.get("day_pnl")
        if current is not None:
            current["actions"].append(ev)
        else:
            bars.append({"bar_time": ev.get("ist_time"), "bucket": None, "score": None,
                         "spot": ev.get("spot"), "bias_votes": None, "leg_status": None,
                         "actions": [ev]})

    return {
        "date": date,
        "strategy_id": strategy_id,
        "summary": {
            "total_bias_events": counts["bias"],
            "total_leg_opens": counts["opens"],
            "total_leg_closes": counts["closes"],
            "total_stops": counts["stops"],
            "total_tps": counts["tps"],
            "total_rolls": counts["rolls"],
            "day_realized_pnl": day_pnl,
            "buckets_seen": buckets_seen,
        },
        "bars": bars,
    }
