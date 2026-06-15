"""Contract-aware writer for the unified ``option_bars`` warehouse.

``option_bars`` is a regular (non-time-series) MongoDB collection with a unique index on the real
contract identity ``(underlying, expiry_date, strike, option_type, timeframe, ts)`` — so duplicate
bars are structurally impossible no matter which producer (live feed or backfill) writes.

Producers build docs with :func:`build_option_bar_doc` and upsert them with first-write-wins
semantics via :func:`option_bar_upserts` (a list of ``UpdateOne`` ops usable by both pymongo, in the
sync backfill scripts, and motor, in the async live feed).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from pymongo import UpdateOne

# The fields that together identify one bar of one physical contract (the unique-index key).
KEY_FIELDS: tuple[str, ...] = (
    "underlying", "expiry_date", "strike", "option_type", "timeframe", "ts",
)


def _expiry_to_dt(expiry_date: date | datetime) -> datetime:
    """Normalise an expiry to a midnight-UTC datetime (BSON has no date type)."""
    if isinstance(expiry_date, datetime):
        return expiry_date.astimezone(UTC)
    return datetime(expiry_date.year, expiry_date.month, expiry_date.day, tzinfo=UTC)


def build_option_bar_doc(
    *,
    underlying: str,
    expiry_date: date | datetime,
    strike: float,
    option_type: str,
    timeframe: str,
    ts: datetime,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: int | None = 0,
    oi: int | None = 0,
    iv: float | None = 0.0,
    expiry_flag: str,
    trading_symbol: str,
    security_id: str | None = None,
    strike_label: str | None = None,
    source: str,
) -> dict[str, Any]:
    """Build one ``option_bars`` document keyed by the real fixed contract."""
    ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return {
        "underlying": underlying.upper(),
        "expiry_date": _expiry_to_dt(expiry_date),
        "strike": float(strike),
        "option_type": option_type.upper(),
        "timeframe": timeframe,
        "ts": ts_utc.astimezone(UTC),
        "open": float(open),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": int(volume or 0),
        "oi": int(oi or 0),
        "iv": float(iv or 0.0),
        "expiry_flag": expiry_flag,
        "trading_symbol": trading_symbol,
        "security_id": security_id,
        "strike_label": strike_label,
        "source": source,
    }


def ensure_option_bars_indexes_sync(collection: Any) -> None:
    """Create the option_bars indexes with a pymongo collection (mirrors ``_ensure_option_bars``).

    Lets sync backfill scripts guarantee the unique contract+ts index exists before bulk upserts,
    without needing the async app to have started. Creating an index auto-creates the (regular)
    collection. Index spec MUST stay in sync with ``pdp.mongo.collections._ensure_option_bars``.
    """
    collection.create_index([(k, 1) for k in KEY_FIELDS], unique=True, name="uq_contract_ts")
    collection.create_index(
        [("underlying", 1), ("expiry_date", 1), ("option_type", 1), ("ts", 1)],
        name="idx_expiry_optype_ts",
    )
    collection.create_index(
        [("underlying", 1), ("strike", 1), ("option_type", 1), ("ts", 1)],
        name="idx_strike_optype_ts",
    )


def option_bar_upserts(docs: Iterable[dict[str, Any]]) -> list[UpdateOne]:
    """First-write-wins upserts: insert a bar only if its (contract, ts) is not already present.

    Works with both pymongo (sync scripts) and motor (async feed) via ``bulk_write``.
    """
    ops: list[UpdateOne] = []
    for d in docs:
        key = {k: d[k] for k in KEY_FIELDS}
        ops.append(UpdateOne(key, {"$setOnInsert": d}, upsert=True))
    return ops


def upsert_option_bars_sync(collection: Any, docs: Iterable[dict[str, Any]]) -> int:
    """Bulk-upsert ``docs`` with a pymongo collection; returns the number of new bars inserted."""
    ops = option_bar_upserts(docs)
    if not ops:
        return 0
    res = collection.bulk_write(ops, ordered=False)
    return res.upserted_count


async def upsert_option_bars_async(collection: Any, docs: Iterable[dict[str, Any]]) -> int:
    """Bulk-upsert ``docs`` with a motor collection; returns the number of new bars inserted."""
    ops = option_bar_upserts(docs)
    if not ops:
        return 0
    res = await collection.bulk_write(ops, ordered=False)
    return res.upserted_count
