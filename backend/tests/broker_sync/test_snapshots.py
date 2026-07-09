from __future__ import annotations

from typing import Any

import pytest

from pdp.broker_sync.backfill import _extract_date, backfill_history
from pdp.broker_sync.snapshots import upsert_snapshot


class FakeCollection:
    """Captures replace_one upserts keyed by the snapshot unique key."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def replace_one(self, flt: dict[str, Any], doc: dict[str, Any], upsert: bool = False) -> None:
        key = (flt["account_id"], flt["snapshot_date"], flt["report_type"])
        self.docs[key] = doc


@pytest.mark.asyncio
async def test_upsert_snapshot_stores_doc_with_count() -> None:
    col = FakeCollection()
    rows = [{"securityId": "1"}, {"securityId": "2"}]
    n = await upsert_snapshot(
        col,
        account_id="A",
        snapshot_date="2026-06-27",
        report_type="holdings",
        rows=rows,
        source="dhan.fetch_holdings",
    )
    assert n == 2
    doc = col.docs[("A", "2026-06-27", "holdings")]
    assert doc["count"] == 2
    assert doc["report_type"] == "holdings"
    assert doc["data"] == rows
    assert doc["source"] == "dhan.fetch_holdings"


@pytest.mark.asyncio
async def test_upsert_snapshot_is_idempotent_by_key() -> None:
    col = FakeCollection()
    await upsert_snapshot(
        col, account_id="A", snapshot_date="2026-06-27", report_type="funds", rows=[{"x": 1}], source="s"
    )
    await upsert_snapshot(
        col, account_id="A", snapshot_date="2026-06-27", report_type="funds", rows=[{"x": 2}], source="s"
    )
    # Same key → single doc, overwritten with the latest payload.
    assert len(col.docs) == 1
    assert col.docs[("A", "2026-06-27", "funds")]["data"] == [{"x": 2}]


def test_extract_date_prefers_known_keys() -> None:
    assert _extract_date({"exchangeTime": "2025-03-14 10:00:00"}, "2025-01-01") == "2025-03-14"
    assert _extract_date({"voucherdate": "2025-03-15"}, "2025-01-01") == "2025-03-15"
    assert _extract_date({"unknown": "x"}, "2025-01-01") == "2025-01-01"  # fallback


class FakeBackfillClient:
    has_credentials = True
    account_id = "A"

    async def fetch_trade_history(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        return [{"tradeDate": "2025-03-14", "id": 1}, {"tradeDate": "2025-03-15", "id": 2}]

    async def fetch_ledger(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        return [{"voucherdate": "2025-03-14", "amt": 10}]


@pytest.mark.asyncio
async def test_backfill_buckets_rows_per_day() -> None:
    col = FakeCollection()
    result = await backfill_history(FakeBackfillClient(), col, from_date="2025-03-01", to_date="2025-03-31")
    assert result["trades"] == 2
    assert result["ledger"] == 1
    # Trades split across two day-docs; ledger one day-doc.
    assert ("A", "2025-03-14", "trades") in col.docs
    assert ("A", "2025-03-15", "trades") in col.docs
    assert ("A", "2025-03-14", "ledger") in col.docs
