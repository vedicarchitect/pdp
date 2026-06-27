"""One-time historical backfill of the transactional logs (trade history + ledger).

Dhan reports holdings/positions/funds only as *current* state, so those cannot be backfilled.
Trade history and ledger are date-ranged: we pull the range, bucket rows by their own date,
and write one immutable ``broker_snapshots`` document per (date, report_type).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

import structlog

from pdp.broker_sync.snapshots import upsert_snapshot

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

    from pdp.broker_sync.client import BrokerAccountClient

log = structlog.get_logger()

# Candidate date fields across Dhan trade/ledger payloads (best-effort).
_DATE_KEYS = ("exchangeTime", "tradeDate", "createTime", "updateTime", "voucherdate", "date", "time")


def _extract_date(row: dict[str, Any], fallback: str) -> str:
    for k in _DATE_KEYS:
        v = row.get(k)
        if isinstance(v, str) and len(v) >= 10:
            # Accept "YYYY-MM-DD..." or "YYYY-MM-DD HH:MM:SS"
            head = v[:10]
            if head[4] == "-" and head[7] == "-":
                return head
    return fallback


async def _backfill_one(
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    *, account_id: str, report_type: str, rows: list[dict[str, Any]], from_date: str, source: str,
) -> int:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        buckets[_extract_date(r, from_date)].append(r)
    for date_str, day_rows in buckets.items():
        await upsert_snapshot(
            col, account_id=account_id, snapshot_date=date_str,
            report_type=report_type, rows=day_rows, source=source,
        )
    return len(rows)


async def backfill_history(
    client: BrokerAccountClient,
    col: AsyncIOMotorCollection,  # type: ignore[type-arg]
    *, from_date: str, to_date: str,
) -> dict[str, Any]:
    """Backfill trade history + ledger for [from_date, to_date]. Returns per-report counts."""
    if not client.has_credentials:
        log.warning("broker_backfill_skipped", reason="no credentials")
        return {"status": "skipped", "trades": 0, "ledger": 0}

    account_id = client.account_id
    result: dict[str, Any] = {"status": "ok"}

    try:
        trades = await client.fetch_trade_history(from_date, to_date)
        result["trades"] = await _backfill_one(
            col, account_id=account_id, report_type="trades", rows=trades,
            from_date=from_date, source="dhan.fetch_trade_history",
        )
    except Exception as exc:
        result["trades_error"] = str(exc)
        log.warning("broker_backfill_failed", report="trades", error=str(exc))

    try:
        ledger = await client.fetch_ledger(from_date, to_date)
        result["ledger"] = await _backfill_one(
            col, account_id=account_id, report_type="ledger", rows=ledger,
            from_date=from_date, source="dhan.fetch_ledger",
        )
    except Exception as exc:
        result["ledger_error"] = str(exc)
        log.warning("broker_backfill_failed", report="ledger", error=str(exc))

    log.info("broker_backfill_done", from_date=from_date, to_date=to_date, result=result)
    return result
