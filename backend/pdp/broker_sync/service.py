"""BrokerSyncService — Dhan account state refresh + daily archival.

Two entry points, deliberately separate:

* ``refresh_state`` — the *intraday* path. Fetches holdings/positions/funds, replaces the PG
  current-state mirror, re-subscribes the feed. No Mongo snapshot, no run row, no reconcile.
  Cheap enough to call every few minutes.
* ``run_daily`` — the *end-of-day* path. Creates a run row → fetches and archives every report to
  Mongo (per-report errors are caught so one bad report doesn't abort the rest) → replaces the PG
  mirror → reconciles broker positions vs the internal ledger → finalizes the run row.

Reconciliation compares the internal ledger against the broker, so it is meaningful only when
orders actually reach the broker. In paper mode it is skipped (``recon.skipped == "paper_mode"``)
rather than emitting a mismatch for every simulated position. It is read-only in all modes.

Credential-less runs are recorded ``skipped`` and never raise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import delete, select

from pdp.broker_sync.models import (
    BrokerFund,
    BrokerHolding,
    BrokerPosition,
    BrokerSyncRun,
    SyncStatus,
    SyncTrigger,
)
from pdp.broker_sync.snapshots import upsert_snapshot
from pdp.orders.models import Position

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pdp.broker_sync.client import BrokerAccountClient

log = structlog.get_logger()

_IST = ZoneInfo("Asia/Kolkata")

# (report_type, source method name) for the per-day archival sweep.
_STATE_REPORTS = (("holdings", "fetch_holdings"), ("positions", "fetch_positions"), ("funds", "fetch_funds"))
_TXN_REPORTS = (("orders", "fetch_orders"), ("trades", "fetch_trades"))

# Triggers that satisfy the EOD idempotency guard. Intraday activity must never pre-empt the
# scheduled archival, so anything else recorded for a date leaves `already_succeeded` false.
_ARCHIVAL_TRIGGERS = (SyncTrigger.AUTO, SyncTrigger.MANUAL)


def ist_today() -> str:
    """Today's Indian trading date as ``YYYY-MM-DD``."""
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _get(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return default


def _num(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


class BrokerSyncService:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        snapshots_col: AsyncIOMotorCollection,  # type: ignore[type-arg]
        client: BrokerAccountClient,
        event_service: Any | None = None,
        live_mode: bool = False,
    ) -> None:
        self._session_maker = session_maker
        self._col = snapshots_col
        self._client = client
        self._adapter: Any | None = None
        self._event_service = event_service  # for POSITION_RECONCILE_MISMATCH alerts
        # Reconcile compares the internal ledger against the broker. Only meaningful when orders
        # actually reach the broker; in paper mode the ledger is simulated and every position
        # would mismatch.
        self._live_mode = live_mode

    def set_market_adapter(self, adapter: Any) -> None:
        self._adapter = adapter

    async def subscribe_current_positions(self) -> None:
        """Subscribe the market feed to every position currently in the PG mirror.

        Shared by ``run_daily`` (post-sync, using the freshly-fetched rows) and app
        startup (using whatever the last sync persisted), so the subscribe-loop logic
        lives in exactly one place.
        """
        if self._adapter is None:
            return
        try:
            async with self._session_maker() as session:
                rows = (await session.scalars(select(BrokerPosition))).all()
                for pos in rows:
                    if pos.security_id and pos.exchange_segment:
                        await self._adapter.subscribe(pos.security_id, pos.exchange_segment, session)
        except Exception as exc:
            log.warning("broker_sync_subscribe_failed", error=str(exc))

    @property
    def account_id(self) -> str:
        return self._client.account_id or "primary"

    @property
    def has_credentials(self) -> bool:
        return self._client.has_credentials

    @property
    def live_mode(self) -> bool:
        return self._live_mode

    async def already_succeeded(self, snapshot_date: str) -> bool:
        async with self._session_maker() as session:
            row = await session.scalar(
                select(BrokerSyncRun).where(
                    BrokerSyncRun.account_id == self.account_id,
                    BrokerSyncRun.snapshot_date == snapshot_date,
                    BrokerSyncRun.status == SyncStatus.OK,
                    BrokerSyncRun.trigger.in_(_ARCHIVAL_TRIGGERS),
                )
            )
            return row is not None

    async def last_run(self) -> dict[str, Any] | None:
        """Most recently started archival run, or ``None`` if none has run today."""
        async with self._session_maker() as session:
            row = await session.scalar(
                select(BrokerSyncRun)
                .where(BrokerSyncRun.account_id == self.account_id)
                .order_by(BrokerSyncRun.started_at.desc())
                .limit(1)
            )
            return _run_dict(row) if row is not None else None

    async def last_state_refresh(self) -> str | None:
        """When the PG mirror was last written, or ``None`` if it never has been.

        The intraday path writes no run row, so ``last_run`` stays ``None`` until the EOD
        archival. This is the signal that tells "never synced" apart from "flat account".
        """
        async with self._session_maker() as session:
            row = await session.scalar(
                select(BrokerFund).where(BrokerFund.account_id == self.account_id)
            )
            return row.synced_at.isoformat() if row is not None and row.synced_at else None

    # ── Intraday: current-state refresh ────────────────────────────────────────
    async def refresh_state(self) -> dict[str, int]:
        """Refresh the PG current-state mirror from the broker.

        The intraday path. Fetches only the three point-in-time reports and replaces the mirror.
        Writes no run row and no Mongo snapshot, so the day's archived snapshot keeps its
        end-of-day meaning and the EOD idempotency guard stays untouched.
        """
        if not self._client.has_credentials:
            log.debug("broker_refresh_skipped_no_creds", account_id=self.account_id)
            return {}

        counts: dict[str, int] = {}
        rows_by_type: dict[str, list[dict[str, Any]]] = {}
        for report_type, method in _STATE_REPORTS:
            rows = await getattr(self._client, method)()
            rows_by_type[report_type] = rows
            counts[report_type] = len(rows)

        await self._replace_mirror(
            self.account_id,
            rows_by_type["holdings"],
            rows_by_type["positions"],
            rows_by_type["funds"],
        )
        await self.subscribe_current_positions()
        log.debug("broker_state_refreshed", account_id=self.account_id, counts=counts)
        return counts

    # ── End of day: full archival ──────────────────────────────────────────────
    async def run_daily(
        self, snapshot_date: str | None = None, trigger: str = SyncTrigger.MANUAL
    ) -> dict[str, Any]:
        date_str = snapshot_date or ist_today()
        account_id = self.account_id

        if not self._client.has_credentials:
            run = await self._record_run(
                account_id,
                date_str,
                trigger,
                SyncStatus.SKIPPED,
                counts={},
                recon=None,
                error="no Dhan credentials",
            )
            log.warning("broker_sync_skipped", account_id=account_id, snapshot_date=date_str)
            return run

        run_id = str(uuid.uuid4())
        await self._open_run(run_id, account_id, date_str, trigger)

        counts: dict[str, int] = {}
        errors: list[str] = []
        holdings: list[dict[str, Any]] = []
        positions: list[dict[str, Any]] = []
        funds: list[dict[str, Any]] = []

        # State reports → archive + keep for the PG mirror.
        for report_type, method in _STATE_REPORTS:
            try:
                rows = await getattr(self._client, method)()
                counts[report_type] = await upsert_snapshot(
                    self._col,
                    account_id=account_id,
                    snapshot_date=date_str,
                    report_type=report_type,
                    rows=rows,
                    source=f"dhan.{method}",
                )
                if report_type == "holdings":
                    holdings = rows
                elif report_type == "positions":
                    positions = rows
                else:
                    funds = rows
            except Exception as exc:
                errors.append(f"{report_type}: {exc}")
                log.warning("broker_sync_report_failed", report_type=report_type, error=str(exc))

        # Transactional reports for the day (orders + trades).
        for report_type, method in _TXN_REPORTS:
            try:
                rows = await getattr(self._client, method)()
                counts[report_type] = await upsert_snapshot(
                    self._col,
                    account_id=account_id,
                    snapshot_date=date_str,
                    report_type=report_type,
                    rows=rows,
                    source=f"dhan.{method}",
                )
            except Exception as exc:
                errors.append(f"{report_type}: {exc}")
                log.warning("broker_sync_report_failed", report_type=report_type, error=str(exc))

        # Ledger for the day (range = single date).
        try:
            rows = await self._client.fetch_ledger(date_str, date_str)
            counts["ledger"] = await upsert_snapshot(
                self._col,
                account_id=account_id,
                snapshot_date=date_str,
                report_type="ledger",
                rows=rows,
                source="dhan.fetch_ledger",
            )
        except Exception as exc:
            errors.append(f"ledger: {exc}")
            log.warning("broker_sync_report_failed", report_type="ledger", error=str(exc))

        recon = await self._replace_state_and_reconcile(account_id, holdings, positions, funds)

        # EOD enhanced reconcile: compare PG vs. broker; emit POSITION_RECONCILE_MISMATCH on mismatch.
        # Live mode only — see `_live_mode`.
        if self._live_mode:
            from pdp.broker_sync.eod_reconcile import reconcile_day_positions

            try:
                eod_recon = await reconcile_day_positions(
                    self._session_maker,
                    broker_positions=positions,
                    event_service=self._event_service,
                )
                recon = {**recon, "eod": eod_recon}
            except Exception as exc:
                log.warning("eod_reconcile_failed", error=str(exc))

        await self.subscribe_current_positions()

        status = SyncStatus.OK if not errors else SyncStatus.PARTIAL
        run = await self._close_run(run_id, status, counts, recon, "; ".join(errors) or None)
        log.info(
            "broker_sync_done", account_id=account_id, snapshot_date=date_str, status=status, counts=counts
        )
        return run

    # ── PG mirror + reconciliation ─────────────────────────────────────────────
    async def _replace_state_and_reconcile(
        self,
        account_id: str,
        holdings: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        funds: list[dict[str, Any]],
    ) -> dict[str, Any]:
        await self._replace_mirror(account_id, holdings, positions, funds)
        if not self._live_mode:
            return {"skipped": "paper_mode"}
        async with self._session_maker() as session:
            return await self._reconcile(session, account_id, positions)

    async def _replace_mirror(
        self,
        account_id: str,
        holdings: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        funds: list[dict[str, Any]],
    ) -> None:
        """Atomically replace this account's PG current-state rows. Shared by both entry points."""
        async with self._session_maker() as session:
            async with session.begin():
                await session.execute(delete(BrokerHolding).where(BrokerHolding.account_id == account_id))
                await session.execute(delete(BrokerPosition).where(BrokerPosition.account_id == account_id))
                for h in holdings:
                    session.add(
                        BrokerHolding(
                            account_id=account_id,
                            security_id=str(_get(h, "securityId", "security_id", default="")),
                            isin=str(_get(h, "isin", default="")),
                            symbol=_get(h, "tradingSymbol", "symbol"),
                            exchange=_get(h, "exchange"),
                            total_qty=_int(_get(h, "totalQty", "totalQuantity", default=0)),
                            available_qty=_int(_get(h, "availableQty", "availableQuantity", default=0)),
                            avg_cost_price=_num(_get(h, "avgCostPrice", "averageCostPrice")),
                            last_price=_num(_get(h, "lastTradedPrice", "ltp")) or None,
                            raw=h,
                        )
                    )
                for p in positions:
                    session.add(
                        BrokerPosition(
                            account_id=account_id,
                            security_id=str(_get(p, "securityId", "security_id", default="")),
                            exchange_segment=str(_get(p, "exchangeSegment", "exchange_segment", default="")),
                            product_type=str(_get(p, "productType", "product", default="")),
                            symbol=_get(p, "tradingSymbol", "symbol"),
                            net_qty=_int(_get(p, "netQty", "net_qty", default=0)),
                            buy_avg=_num(_get(p, "buyAvg", "buyAvgPrice")),
                            sell_avg=_num(_get(p, "sellAvg", "sellAvgPrice")),
                            realized_pnl=_num(_get(p, "realizedProfit", "realized_pnl")),
                            unrealized_pnl=_num(_get(p, "unrealizedProfit", "unrealized_pnl")),
                            raw=p,
                        )
                    )
                fund = funds[0] if funds else {}
                if fund:
                    await session.execute(delete(BrokerFund).where(BrokerFund.account_id == account_id))
                    session.add(
                        BrokerFund(
                            account_id=account_id,
                            available_balance=_num(_get(fund, "availabelBalance", "availableBalance")),
                            utilized_amount=_num(_get(fund, "utilizedAmount")),
                            collateral_amount=_num(_get(fund, "collateralAmount")),
                            withdrawable_balance=_num(_get(fund, "withdrawableBalance")),
                            raw=fund,
                        )
                    )

    async def _reconcile(
        self, session: AsyncSession, account_id: str, broker_positions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # Aggregate internal net qty by security_id across strategies.
        internal: dict[str, int] = {}
        for pos in (await session.scalars(select(Position))).all():
            internal[pos.security_id] = internal.get(pos.security_id, 0) + int(pos.net_qty)

        broker: dict[str, int] = {}
        for p in broker_positions:
            sid = str(_get(p, "securityId", "security_id", default=""))
            if sid:
                broker[sid] = broker.get(sid, 0) + _int(_get(p, "netQty", "net_qty", default=0))

        mismatches: list[dict[str, Any]] = []
        for sid in set(internal) | set(broker):
            iqty, bqty = internal.get(sid, 0), broker.get(sid, 0)
            if iqty != bqty:
                mismatches.append({"security_id": sid, "internal": iqty, "broker": bqty})
                log.warning(
                    "broker_recon_mismatch",
                    account_id=account_id,
                    security_id=sid,
                    internal=iqty,
                    broker=bqty,
                )
        return {"checked": len(set(internal) | set(broker)), "mismatches": mismatches}

    # ── Run-row lifecycle ──────────────────────────────────────────────────────
    async def _open_run(self, run_id: str, account_id: str, date_str: str, trigger: str) -> None:
        async with self._session_maker() as session:
            async with session.begin():
                session.add(
                    BrokerSyncRun(
                        id=run_id,
                        account_id=account_id,
                        snapshot_date=date_str,
                        trigger=trigger,
                        status=SyncStatus.RUNNING,
                    )
                )

    async def _close_run(
        self,
        run_id: str,
        status: str,
        counts: dict[str, int],
        recon: dict[str, Any] | None,
        error: str | None,
    ) -> dict[str, Any]:
        async with self._session_maker() as session:
            async with session.begin():
                run = await session.get(BrokerSyncRun, run_id)
                if run is not None:
                    run.status = status
                    run.counts = counts
                    run.recon = recon
                    run.error = error
                    run.finished_at = datetime.now(UTC)
            return _run_dict(run) if run is not None else {}

    async def _record_run(
        self,
        account_id: str,
        date_str: str,
        trigger: str,
        status: str,
        counts: dict[str, int],
        recon: dict[str, Any] | None,
        error: str | None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        async with self._session_maker() as session:
            async with session.begin():
                run = BrokerSyncRun(
                    id=run_id,
                    account_id=account_id,
                    snapshot_date=date_str,
                    trigger=trigger,
                    status=status,
                    counts=counts,
                    recon=recon,
                    error=error,
                    finished_at=datetime.now(UTC),
                )
                session.add(run)
            return _run_dict(run)


def _run_dict(run: BrokerSyncRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "account_id": run.account_id,
        "snapshot_date": run.snapshot_date,
        "trigger": run.trigger,
        "status": run.status,
        "counts": run.counts or {},
        "recon": run.recon,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
