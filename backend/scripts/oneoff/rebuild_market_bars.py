"""One-off rebuild of derived market_bars timeframes onto the session-anchored grid.

Context: bar-session-anchoring (openspec/changes/bar-session-anchoring) moved bucket
boundaries for 25m/30m/1H from Unix-epoch anchoring to 09:15 IST session-open anchoring.
Historical bars stored under the old anchoring are on the wrong grid for those three
timeframes (5m/15m/1D/1w are unaffected — see bars.py's docstrings for why). This script
recomputes 15m/30m/1H (and, on request, 5m — its bucket boundaries were never wrong, but
`--timeframes 5m` is useful to re-derive 5m bars that a live-process outage simply never
produced, e.g. `indicator-matrix-kite-parity`'s 2026-07-13 coverage gap) from the stored
1m bars (which are timeframe-agnostic prints and don't need rebuilding themselves) and
replaces them via delete-then-insert, since market_bars is a MongoDB time-series
collection with no in-place update.

Rolls up from stored 1m OHLCV docs rather than replaying through BarAggregator/BarBuilder
(which are tick-oriented and expect one LTP per push): a 1m bar's own OHLC already carries
full intra-minute fidelity, and reducing it back to a single synthetic tick per minute would
throw that away. It reuses `_bar_boundary` — the same bucket function the live feed calls —
via aggregate(open=first, high=max, low=min, close=last, volume=sum), so the anchoring math
itself has exactly one implementation in the codebase.

Usage:
    uv run python scripts/oneoff/rebuild_market_bars.py --underlying NIFTY \
        --from 2026-06-01 --to 2026-07-10 --dry-run
    # --all-sids also rebuilds option-leg contract bars, not just the named indices:
    uv run python scripts/oneoff/rebuild_market_bars.py --all-sids \
        --from 2026-06-01 --to 2026-07-10 --dry-run
    uv run python scripts/oneoff/rebuild_market_bars.py --all-sids \
        --from 2026-06-01 --to 2026-07-10
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from pdp.market.bars import _bar_boundary
from pdp.mongo import client as mongo_client
from pdp.mongo.collections import get_bars_collection
from pdp.settings import get_settings
from pdp.warehouse.service import SID_MAP

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = structlog.get_logger()

# label -> minutes. 15m/30m/1H moved off the epoch grid (bar-session-anchoring); 5m did
# not (225 min from UTC midnight to the 09:15 IST session open divides evenly by 5), but
# is included so this script can also re-derive 5m bars a live-process outage dropped.
_REBUILD_TIMEFRAMES: dict[str, int] = {"5m": 5, "15m": 15, "30m": 30, "1H": 60}


async def discover_security_ids(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    timeframes: list[str],
    start: datetime,
    end: datetime,
) -> list[str]:
    """Every security_id with an existing 15m/30m/1H bar in range — the true rebuild scope.

    market_bars holds far more than the 4 named indices: any instrument the live feed ever
    subscribed to (e.g. a strangle leg's option contract, for as long as the position was
    open) gets its own bars across every configured timeframe. Scoping the rebuild to
    SID_MAP's 4 names would silently skip most of the affected data.
    """
    pipeline = [
        {"$match": {"metadata.timeframe": {"$in": timeframes}, "ts": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": "$metadata.security_id"}},
    ]
    return sorted([row["_id"] async for row in col.aggregate(pipeline)])


async def _load_1m_bars(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    security_id: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    cursor = col.find(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": "1m",
            "ts": {"$gte": start, "$lt": end},
        }
    ).sort("ts", 1)
    return [doc async for doc in cursor]


def rollup_bars(bars_1m: list[dict[str, Any]], tf_minutes: int, tf_label: str) -> list[dict[str, Any]]:
    """Roll up 1m OHLCV docs into tf_minutes buckets, anchored via `_bar_boundary`."""
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for doc in bars_1m:
        ts = doc["ts"] if doc["ts"].tzinfo else doc["ts"].replace(tzinfo=UTC)
        boundary = _bar_boundary(ts, tf_minutes)
        buckets.setdefault(boundary, []).append(doc)

    out: list[dict[str, Any]] = []
    for boundary in sorted(buckets):
        group = sorted(buckets[boundary], key=lambda d: d["ts"])
        out.append(
            {
                "ts": boundary,
                "metadata": {
                    "security_id": group[0]["metadata"]["security_id"],
                    "timeframe": tf_label,
                },
                "open": group[0]["open"],
                "high": max(d["high"] for d in group),
                "low": min(d["low"] for d in group),
                "close": group[-1]["close"],
                "volume": sum(d.get("volume", 0) for d in group),
                "oi": group[-1].get("oi"),
            }
        )
    return out


async def rebuild_one(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    security_id: str,
    tf_label: str,
    start: datetime,
    end: datetime,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    tf_minutes = _REBUILD_TIMEFRAMES[tf_label]
    bars_1m = await _load_1m_bars(col, security_id, start, end)
    new_docs = rollup_bars(bars_1m, tf_minutes, tf_label)

    range_query = {
        "metadata.security_id": security_id,
        "metadata.timeframe": tf_label,
        "ts": {"$gte": start, "$lt": end},
    }
    existing_count = await col.count_documents(range_query)
    summary = {
        "security_id": security_id,
        "timeframe": tf_label,
        "existing_count": existing_count,
        "new_count": len(new_docs),
        "first_ts": new_docs[0]["ts"] if new_docs else None,
        "last_ts": new_docs[-1]["ts"] if new_docs else None,
    }
    if dry_run or not new_docs:
        return summary

    await col.delete_many(range_query)
    await col.insert_many(new_docs, ordered=False)
    return summary


async def _run(
    *,
    underlyings: list[str] | None,
    all_sids: bool,
    start_d: date,
    end_d: date,
    timeframes: list[str],
    dry_run: bool,
) -> None:
    settings = get_settings()
    client, db = mongo_client.connect(settings)
    col = get_bars_collection(db)
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=UTC)
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=UTC) + timedelta(days=1)
    try:
        if all_sids:
            sids = await discover_security_ids(col, timeframes, start, end)
            log.info("rebuild_scope_discovered", sid_count=len(sids))
        else:
            assert underlyings is not None
            sids = [SID_MAP[name] for name in underlyings]

        for sid in sids:
            for tf in timeframes:
                summary = await rebuild_one(col, sid, tf, start, end, dry_run=dry_run)
                log.info("rebuild_summary", dry_run=dry_run, **summary)
    finally:
        mongo_client.disconnect(client)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--underlying",
        choices=sorted(SID_MAP),
        action="append",
        help="One or more named underlyings (repeatable). Only touches these security_ids.",
    )
    scope.add_argument(
        "--all-sids",
        action="store_true",
        help="Discover and rebuild every security_id with an existing bar in range, not just "
        "the named underlyings — needed to cover option-leg bars from live trading.",
    )
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, required=True)
    parser.add_argument(
        "--timeframes",
        nargs="+",
        choices=sorted(_REBUILD_TIMEFRAMES),
        default=list(_REBUILD_TIMEFRAMES),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(
        _run(
            underlyings=args.underlying,
            all_sids=args.all_sids,
            start_d=args.start,
            end_d=args.end,
            timeframes=args.timeframes,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
