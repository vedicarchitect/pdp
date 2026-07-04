"""backtest-paper-comparison: index orders.strategy_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-04

Supports the per-strategy paper realized-P&L query (trades JOIN orders, grouped by
orders.strategy_id) used by the backtest-vs-paper comparison — only positions.strategy_id
was indexed before this.
"""
from __future__ import annotations

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_orders_strategy_id", "orders", ["strategy_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_strategy_id", table_name="orders")
