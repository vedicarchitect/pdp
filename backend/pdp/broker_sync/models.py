"""PostgreSQL current-state mirror + run audit for broker account sync.

These tables hold only the **latest** broker snapshot (replaced atomically each run) for fast
queries/joins and reconciliation. The immutable history lives in MongoDB `broker_snapshots`.
Every row is keyed by ``account_id`` so a second broker/account (chunk 15) slots in unchanged.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pdp.db.base import Base


class SyncStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncTrigger(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    BACKFILL = "backfill"


class BrokerSyncRun(Base):
    """Audit + idempotency log: one row per sync attempt for an account+date."""

    __tablename__ = "broker_sync_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4 hex-with-dashes
    account_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    broker: Mapped[str] = mapped_column(String, nullable=False, default="dhan")
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=SyncStatus.RUNNING)
    counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {report_type: row_count}
    recon: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # reconciliation summary
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrokerHolding(Base):
    """Latest holdings snapshot (equity/MF). Replaced each successful sync."""

    __tablename__ = "broker_holdings"
    __table_args__ = (
        UniqueConstraint("account_id", "security_id", "isin", name="uq_broker_holdings_acct_sid_isin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    isin: Mapped[str] = mapped_column(String, nullable=False, default="")
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    total_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerPosition(Base):
    """Latest positions snapshot (F&O + intraday). Replaced each successful sync."""

    __tablename__ = "broker_positions"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "security_id", "exchange_segment", "product_type",
            name="uq_broker_positions_acct_sid_seg_prod",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String, nullable=False)
    product_type: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    net_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buy_avg: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    sell_avg: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerFund(Base):
    """Latest fund limits — one row per account. Replaced each successful sync."""

    __tablename__ = "broker_funds"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    utilized_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    collateral_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    withdrawable_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
