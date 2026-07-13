"""backtest tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-08

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(), nullable=False, index=True),
        sa.Column("from_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_equity", sa.Numeric(14, 4), nullable=False),
        sa.Column("end_equity", sa.Numeric(14, 4), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False, index=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("exit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(14, 4), nullable=False),
        sa.Column("strategy_metadata", sa.JSON(), nullable=True),
    )

    op.create_table(
        "backtest_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False, index=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starting_equity", sa.Numeric(14, 4), nullable=False),
        sa.Column("ending_equity", sa.Numeric(14, 4), nullable=False),
        sa.Column("daily_pnl", sa.Numeric(14, 4), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_drawdown", sa.Numeric(14, 4), nullable=False),
        sa.Column("current_drawdown_pct", sa.Numeric(14, 4), nullable=False),
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_daily_run_id", table_name="backtest_daily")
    op.drop_table("backtest_daily")
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtest_runs_strategy_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
