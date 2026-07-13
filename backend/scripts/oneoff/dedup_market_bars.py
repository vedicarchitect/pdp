"""One-off dedup of duplicate `market_bars` documents outside the range the
bar-session-anchoring rebuild already corrected (2026-04-08 to 2026-07-11).

Context: `market_bars` is a MongoDB time-series collection with no unique index (see
`pdp/market/CLAUDE.md`); `BarWriter._flush()` used a plain `insert_many` with no
pre-existence check until `market-bars-duplicate-write-fix` made it idempotent
(delete-then-insert per bucket in `bar_writer.py`). That fix stops *new* duplicates —
it does not remove ones already written. A scoped audit (2026-07-13) found 510
duplicate `(security_id, timeframe, ts)` buckets in the 2026-01-01 to 2026-04-08
window alone (2025 sample windows showed none), confirming duplication predates the
already-fixed range.

For each duplicate bucket this script keeps the document with the highest `volume`
(the best proxy for "most complete aggregation" — see `test_late_tick_after_flush_...`
in `tests/market/test_bar_boundary.py` for why a *later* write from a re-opened bucket
is typically a low-volume fragment, not an improvement) and deletes the rest.

Usage:
    # Always back up first (see docs/RUNBOOK.md "Rebuild session-anchored bars" for the
    # JSONL export/restore snippets — the same approach applies here).
    uv run python scripts/oneoff/dedup_market_bars.py --from 2026-01-01 --to 2026-04-08 --dry-run
    uv run python scripts/oneoff/dedup_market_bars.py --from 2026-01-01 --to 2026-04-08
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from pdp.mongo import client as mongo_client
from pdp.mongo.collections import get_bars_collection
from pdp.settings import get_settings

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = structlog.get_logger()


async def find_duplicate_buckets(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Every `(security_id, timeframe, ts)` bucket with more than one document in range."""
    pipeline = [
        {"$match": {"ts": {"$gte": start, "$lt": end}}},
        {
            "$group": {
                "_id": {
                    "sid": "$metadata.security_id",
                    "tf": "$metadata.timeframe",
                    "ts": "$ts",
                },
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]
    return [row async for row in col.aggregate(pipeline)]


async def _backup_bucket(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    sid: str,
    tf: str,
    ts: datetime,
    backup_path: Path,
) -> list[dict[str, Any]]:
    docs = await col.find(
        {"metadata.security_id": sid, "metadata.timeframe": tf, "ts": ts}
    ).to_list(length=None)
    with backup_path.open("a") as f:
        for doc in docs:
            out = dict(doc)
            out["_id"] = str(out["_id"])
            out["ts"] = out["ts"].isoformat()
            f.write(json.dumps(out) + "\n")
    return docs


def _pick_survivor(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Highest `volume` wins; ties broken by the largest `_id` (most recently inserted)."""
    return max(docs, key=lambda d: (d.get("volume", 0), str(d["_id"])))


async def dedup_one(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    sid: str,
    tf: str,
    ts: datetime,
    backup_path: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    docs = await _backup_bucket(col, sid, tf, ts, backup_path)
    survivor = _pick_survivor(docs)
    removed_ids = [d["_id"] for d in docs if d["_id"] != survivor["_id"]]
    summary = {
        "security_id": sid,
        "timeframe": tf,
        "ts": ts.isoformat(),
        "duplicate_count": len(docs),
        "kept_volume": survivor.get("volume"),
        "removed_count": len(removed_ids),
    }
    if dry_run or not removed_ids:
        return summary

    await col.delete_many(
        {
            "metadata.security_id": sid,
            "metadata.timeframe": tf,
            "ts": ts,
        }
    )
    await col.insert_one(survivor)
    return summary


async def _run(*, start_d: date, end_d: date, dry_run: bool, backup_path: Path) -> None:
    settings = get_settings()
    client, db = mongo_client.connect(settings)
    col = get_bars_collection(db)
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=UTC)
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=UTC) + timedelta(days=1)
    try:
        buckets = await find_duplicate_buckets(col, start, end)
        log.info("dedup_scope_discovered", duplicate_bucket_count=len(buckets), dry_run=dry_run)
        if not buckets:
            return

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        total_removed = 0
        for row in buckets:
            key = row["_id"]
            summary = await dedup_one(
                col, key["sid"], key["tf"], key["ts"], backup_path, dry_run=dry_run
            )
            total_removed += summary["removed_count"]
            log.info("dedup_bucket", **summary)

        log.info(
            "dedup_done",
            dry_run=dry_run,
            buckets_processed=len(buckets),
            docs_removed=total_removed if not dry_run else 0,
            backup_path=str(backup_path),
        )
    finally:
        mongo_client.disconnect(client)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--backup-path",
        type=Path,
        default=Path("data/backups/market_bars_dedup_backup.jsonl"),
        help="Every duplicate document (kept and removed) is appended here before any delete.",
    )
    args = parser.parse_args()

    asyncio.run(
        _run(start_d=args.start, end_d=args.end, dry_run=args.dry_run, backup_path=args.backup_path)
    )


if __name__ == "__main__":
    main()
