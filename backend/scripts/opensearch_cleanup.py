"""Retention cleanup for the OpenSearch log pipeline (dev disk/CPU control).

Every family except `pdp-trades-*` ("tradelogs", kept as the durable reference) is
pruned to a rolling window (default 7 days): whole indices past the window are dropped
outright; the current, still-partially-in-window index is trimmed with delete_by_query
on `@timestamp`. Indices are monthly-suffixed (see `pdp/observability/indexer.py`), so a
past month is only ever "whole index" or "fully outside the window" — never both.

Usage:
  uv run python scripts/opensearch_cleanup.py                  # apply, 7-day window
  uv run python scripts/opensearch_cleanup.py --days 14
  uv run python scripts/opensearch_cleanup.py --dry-run         # print plan only
  uv run python scripts/opensearch_cleanup.py --keep-prefix trades,journal
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import os
import re
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import structlog  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pdp.observability.client import close_opensearch, get_opensearch  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

log = structlog.get_logger("pdp.observability.cleanup").bind(_no_ship=True)

_INDEX_RE = re.compile(r"^(?P<prefix>[a-z0-9]+)-(?P<family>[a-z-]+)-(?P<year>\d{4})\.(?P<month>\d{2})$")


def _month_end(year: int, month: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC)


async def cleanup(*, days: int, keep_prefixes: list[str], dry_run: bool) -> None:
    settings = get_settings()
    if not settings.OPENSEARCH_ENABLED:
        log.warning("opensearch_disabled", hint="set OPENSEARCH_ENABLED=true")
        return

    client = get_opensearch()
    assert client is not None
    prefix = settings.OPENSEARCH_INDEX_PREFIX
    cutoff = datetime.now(UTC) - timedelta(days=days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    resp = await client.cat.indices(index=f"{prefix}-*", format="json")
    indices = sorted(row["index"] for row in resp)

    to_delete: list[str] = []
    to_trim: list[str] = []
    for name in indices:
        m = _INDEX_RE.match(name)
        if not m:
            continue
        family = m["family"]
        if any(family == kp or family.startswith(f"{kp}-") for kp in keep_prefixes):
            continue
        year, month = int(m["year"]), int(m["month"])
        if _month_end(year, month) < cutoff:
            to_delete.append(name)
        else:
            to_trim.append(name)

    log.info(
        "cleanup_plan",
        cutoff=cutoff_iso,
        keep_prefixes=keep_prefixes,
        delete_whole=to_delete,
        trim_partial=to_trim,
        dry_run=dry_run,
    )

    if dry_run:
        print(f"[dry-run] would delete {len(to_delete)} whole indices: {to_delete}")
        print(f"[dry-run] would delete_by_query (@timestamp < {cutoff_iso}) on: {to_trim}")
        await close_opensearch()
        return

    for name in to_delete:
        await client.indices.delete(index=name)
        print(f"deleted index: {name}")

    for name in to_trim:
        result = await client.delete_by_query(
            index=name,
            body={"query": {"range": {"@timestamp": {"lt": cutoff_iso}}}},
            conflicts="proceed",
        )
        deleted = result.get("deleted", 0)
        print(f"trimmed {name}: deleted {deleted} docs older than {cutoff_iso}")

    await close_opensearch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="retention window in days (default 7)")
    parser.add_argument(
        "--keep-prefix",
        default="trades",
        help="comma-separated family prefixes to keep forever (default: trades)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan without deleting")
    args = parser.parse_args()

    keep_prefixes = [p.strip() for p in args.keep_prefix.split(",") if p.strip()]
    asyncio.run(cleanup(days=args.days, keep_prefixes=keep_prefixes, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
