"""broker-account-sync: current-state mirror + run audit tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-27

Chunk 2 (broker-account-sync). Adds the PostgreSQL current-state mirror (broker_holdings,
broker_positions, broker_funds) and the run audit/idempotency log (broker_sync_run). The
immutable daily history lives in MongoDB (broker_snapshots), not here.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_sync_run",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("broker", sa.String(), nullable=False, server_default="dhan"),
        sa.Column("snapshot_date", sa.String(length=10), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("recon", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_broker_sync_run_account_id", "broker_sync_run", ["account_id"])
    op.create_index("ix_broker_sync_run_snapshot_date", "broker_sync_run", ["snapshot_date"])

    op.create_table(
        "broker_holdings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False, server_default=""),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("total_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_cost_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("last_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "security_id", "isin", name="uq_broker_holdings_acct_sid_isin"),
    )
    op.create_index("ix_broker_holdings_account_id", "broker_holdings", ["account_id"])

    op.create_table(
        "broker_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column("product_type", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("net_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy_avg", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("sell_avg", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "account_id", "security_id", "exchange_segment", "product_type",
            name="uq_broker_positions_acct_sid_seg_prod",
        ),
    )
    op.create_index("ix_broker_positions_account_id", "broker_positions", ["account_id"])

    op.create_table(
        "broker_funds",
        sa.Column("account_id", sa.String(), primary_key=True),
        sa.Column("available_balance", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("utilized_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("collateral_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("withdrawable_balance", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("broker_funds")
    op.drop_index("ix_broker_positions_account_id", table_name="broker_positions")
    op.drop_table("broker_positions")
    op.drop_index("ix_broker_holdings_account_id", table_name="broker_holdings")
    op.drop_table("broker_holdings")
    op.drop_index("ix_broker_sync_run_snapshot_date", table_name="broker_sync_run")
    op.drop_index("ix_broker_sync_run_account_id", table_name="broker_sync_run")
    op.drop_table("broker_sync_run")
