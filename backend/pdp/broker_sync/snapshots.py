"""MongoDB immutable daily archive for broker reports.

One document per ``(account_id, snapshot_date, report_type)`` in the regular collection
``broker_snapshots``. Idempotent: re-running a date upserts (overwrites) its document, never
duplicates. Mirrors the existing daily-doc pattern (``portfolio_snapshots``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

log = structlog.get_logger()

# State + transactional report types archived per day.
REPORT_TYPES = ("holdings", "positions", "funds", "orders", "trades", "ledger")


async def upsert_snapshot(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    *,
    account_id: str,
    snapshot_date: str,
    report_type: str,
    rows: list[dict[str, Any]],
    source: str,
    broker: str = "dhan",
) -> int:
    """Upsert one daily broker-report document. Returns the row count stored."""
    doc = {
        "account_id": account_id,
        "broker": broker,
        "snapshot_date": snapshot_date,
        "report_type": report_type,
        "captured_at": datetime.now(UTC),
        "source": source,
        "count": len(rows),
        "data": rows,
    }
    await col.replace_one(
        {"account_id": account_id, "snapshot_date": snapshot_date, "report_type": report_type},
        doc,
        upsert=True,
    )
    log.debug(
        "broker_snapshot_upserted",
        account_id=account_id,
        snapshot_date=snapshot_date,
        report_type=report_type,
        count=len(rows),
    )
    return len(rows)


async def get_snapshot(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    *,
    account_id: str,
    snapshot_date: str,
    report_type: str,
) -> dict[str, Any] | None:
    return await col.find_one(
        {"account_id": account_id, "snapshot_date": snapshot_date, "report_type": report_type},
        {"_id": 0},
    )
