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


async def _seed_internal_position(net_qty: int = 50) -> None:
    async with get_session_maker()() as s:
        async with s.begin():
            s.add(
                Position(
                    security_id="888", exchange_segment="NSE_FNO", product="INTRADAY", net_qty=net_qty
                )
            )


@pytest.mark.asyncio
async def test_reconcile_flags_mismatch_in_live_mode(clean: Any) -> None:
    # Internal ledger says 50 for sid 888; broker reports 25 → mismatch.
    await _seed_internal_position(50)
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient(), live_mode=True)
    run = await svc.run_daily("2026-06-27")
    mismatches = run["recon"]["mismatches"]
    assert any(m["security_id"] == "888" and m["internal"] == 50 and m["broker"] == 25 for m in mismatches)


@pytest.mark.asyncio
async def test_reconcile_does_not_mutate_positions(clean: Any) -> None:
    await _seed_internal_position(50)
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient(), live_mode=True)
    await svc.run_daily("2026-06-27")
    async with get_session_maker()() as s:
        pos = await s.scalar(select(Position).where(Position.security_id == "888"))
    assert pos is not None and pos.net_qty == 50


@pytest.mark.asyncio
async def test_reconcile_skipped_in_paper_mode(clean: Any) -> None:
    """Paper Positions have no broker counterpart; reconciling them alerts on every leg."""
    await _seed_internal_position(50)
    events: list[Any] = []

    class _RecordingEvents:
        def emit_critical(self, *args: Any, **kwargs: Any) -> None:
            events.append(args)

    svc = BrokerSyncService(
        get_session_maker(), FakeCollection(), FakeClient(), event_service=_RecordingEvents()
    )
    run = await svc.run_daily("2026-06-27")

    assert run["status"] == SyncStatus.OK
    assert run["recon"] == {"skipped": "paper_mode"}
    assert events == []


@pytest.mark.asyncio
async def test_refresh_state_writes_mirror_but_no_run_or_snapshot(clean: Any) -> None:
    col = FakeCollection()
    svc = BrokerSyncService(get_session_maker(), col, FakeClient())
    counts = await svc.refresh_state()

    assert counts == {"holdings": 1, "positions": 1, "funds": 1}
    assert col.docs == {}, "intraday refresh must not overwrite the day's Mongo snapshot"

    async with get_session_maker()() as s:
        holdings = (await s.scalars(select(BrokerHolding).where(BrokerHolding.account_id == ACCT))).all()
        runs = (await s.scalars(select(BrokerSyncRun).where(BrokerSyncRun.account_id == ACCT))).all()
    assert len(holdings) == 1
    assert runs == [], "intraday refresh must not write a run row"


@pytest.mark.asyncio
async def test_last_state_refresh_distinguishes_never_synced(clean: Any) -> None:
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient())
    assert await svc.last_state_refresh() is None
    await svc.refresh_state()
    assert await svc.last_state_refresh() is not None


@pytest.mark.asyncio
async def test_refresh_state_without_credentials_is_a_noop(clean: Any) -> None:
    client = FakeClient()
    client.has_credentials = False
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), client)
    assert await svc.refresh_state() == {}


@pytest.mark.asyncio
async def test_intraday_activity_does_not_preempt_eod_archival(clean: Any) -> None:
    """A day of intraday activity must leave the 15:45 archival still due."""
    svc = BrokerSyncService(get_session_maker(), FakeCollection(), FakeClient())
    await svc.refresh_state()
    assert await svc.already_succeeded("2026-06-27") is False

    # Defense in depth: even a stray OK run recorded under a non-archival trigger must not
    # satisfy the scheduler's idempotency guard.
    async with get_session_maker()() as s:
        async with s.begin():
            s.add(
                BrokerSyncRun(
                    id="intraday-1",
                    account_id=ACCT,
                    snapshot_date="2026-06-27",
                    trigger="intraday_poll",
                    status=SyncStatus.OK,
                )
            )
    assert await svc.already_succeeded("2026-06-27") is False

    await svc.run_daily("2026-06-27", trigger="auto")
    assert await svc.already_succeeded("2026-06-27") is True


@pytest.mark.asyncio
async def test_default_snapshot_date_is_ist(clean: Any) -> None:
    from datetime import UTC, datetime
    from unittest.mock import patch

    import pdp.broker_sync.service as service_mod

    # 19:30 UTC on 2026-07-09 is 01:00 IST on 2026-07-10.
    frozen = datetime(2026, 7, 9, 19, 30, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return frozen.astimezone(tz) if tz else frozen

    with patch.object(service_mod, "datetime", _FrozenDatetime):
        assert service_mod.ist_today() == "2026-07-10"
