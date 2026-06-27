from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select

from pdp.broker_sync.models import (
    BrokerFund,
    BrokerHolding,
    BrokerPosition,
    BrokerSyncRun,
    SyncStatus,
)
from pdp.broker_sync.service import BrokerSyncService
from pdp.db.session import get_session_maker
from pdp.orders.models import Position

ACCT = "TEST_ACCT"


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def replace_one(self, flt: dict[str, Any], doc: dict[str, Any], upsert: bool = False) -> None:
        self.docs[(flt["account_id"], flt["snapshot_date"], flt["report_type"])] = doc


class FakeClient:
    has_credentials = True
    account_id = ACCT

    def __init__(self, fail_report: str | None = None, positions: list[dict[str, Any]] | None = None) -> None:
        self._fail = fail_report
        self._positions = positions if positions is not None else [
            {"securityId": "888", "exchangeSegment": "NSE_FNO", "productType": "INTRADAY", "netQty": 25}
        ]

    async def fetch_holdings(self) -> list[dict[str, Any]]:
        if self._fail == "holdings":
            raise RuntimeError("boom")
        return [{"securityId": "100", "isin": "IN100", "totalQty": 5, "avgCostPrice": "120.5"}]

    async def fetch_positions(self) -> list[dict[str, Any]]:
        return self._positions

    async def fetch_funds(self) -> list[dict[str, Any]]:
        return [{"availabelBalance": "10000.5", "utilizedAmount": "500"}]

    async def fetch_orders(self) -> list[dict[str, Any]]:
        return [{"orderId": "o1"}]

    async def fetch_trades(self) -> list[dict[str, Any]]:
        return [{"tradeId": "t1"}]

    async def fetch_ledger(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        return [{"voucherdate": from_date, "amount": "100"}]


async def _purge() -> None:
    async with get_session_maker()() as s:
        async with s.begin():
            await s.execute(delete(BrokerHolding).where(BrokerHolding.account_id == ACCT))
            await s.execute(delete(BrokerPosition).where(BrokerPosition.account_id == ACCT))
            await s.execute(delete(BrokerFund).where(BrokerFund.account_id == ACCT))
            await s.execute(delete(BrokerSyncRun).where(BrokerSyncRun.account_id == ACCT))
            await s.execute(delete(Position).where(Position.security_id.in_(["888"])))


@pytest.fixture
async def clean() -> Any:
    await _purge()
    yield
    await _purge()


@pytest.mark.asyncio
async def test_run_daily_ok_archives_and_mirrors(clean: Any) -> None:
    col = FakeCollection()
    svc = BrokerSyncService(get_session_maker(), col, FakeClient())
    run = await svc.run_daily("2026-06-27", trigger="manual")

    assert run["status"] == SyncStatus.OK
    assert run["counts"]["holdings"] == 1
    assert set(run["counts"]) == {"holdings", "positions", "funds", "orders", "trades", "ledger"}
    # Mongo archive captured every report type.
    assert (ACCT, "2026-06-27", "ledger") in col.docs

    async with get_session_maker()() as s:
        holdings = (await s.scalars(select(BrokerHolding).where(BrokerHolding.account_id == ACCT))).all()
        funds = await s.scalar(select(BrokerFund).where(BrokerFund.account_id == ACCT))
        run_row = await s.scalar(select(BrokerSyncRun).where(BrokerSyncRun.account_id == ACCT))
    assert len(holdings) == 1 and holdings[0].avg_cost_price == Decimal("120.5000")
    assert funds is not None and funds.available_balance == Decimal("10000.5000")
    assert run_row is not None and run_row.status == SyncStatus.OK


@pytest.mark.asyncio
async def test_run_daily_skipped_without_credentials(clean: Any) -> None:
    client = FakeClient()
    client.has_credentials = False
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), client)
    run = await svc.run_daily("2026-06-27")
    assert run["status"] == SyncStatus.SKIPPED


@pytest.mark.asyncio
async def test_run_daily_partial_on_report_error(clean: Any) -> None:
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient(fail_report="holdings"))
    run = await svc.run_daily("2026-06-27")
    assert run["status"] == SyncStatus.PARTIAL
    assert "holdings" in (run["error"] or "")


@pytest.mark.asyncio
async def test_reconcile_flags_mismatch(clean: Any) -> None:
    # Internal ledger says 50 for sid 888; broker reports 25 → mismatch.
    async with get_session_maker()() as s:
        async with s.begin():
            s.add(Position(security_id="888", exchange_segment="NSE_FNO", product="INTRADAY", net_qty=50))
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient())
    run = await svc.run_daily("2026-06-27")
    mismatches = run["recon"]["mismatches"]
    assert any(m["security_id"] == "888" and m["internal"] == 50 and m["broker"] == 25 for m in mismatches)
