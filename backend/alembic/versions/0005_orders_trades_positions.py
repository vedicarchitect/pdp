"""orders trades positions

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_order_id", sa.String(), nullable=True),
        sa.Column("broker", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(14, 4), nullable=True),
        sa.Column("trigger_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(), nullable=True),
        sa.Column("strategy_id", sa.String(), nullable=True),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )
    op.create_index("ix_orders_security_status", "orders", ["security_id", "status"])
    op.create_index("ix_orders_placed_at", "orders", ["placed_at"])

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Numeric(14, 4), nullable=False),
        sa.Column(
            "slippage_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column("charges", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column(
            "filled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_trades_order_id", "trades", ["order_id"])
    op.create_index("ix_trades_security_id", "trades", ["security_id"])

    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("net_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "avg_price", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "realized_pnl", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "unrealized_pnl", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "security_id",
            "exchange_segment",
            "product",
            name="uq_positions_sid_seg_product",
        ),
    )
    op.create_index("ix_positions_security_id", "positions", ["security_id"])


def downgrade() -> None:
    op.drop_index("ix_positions_security_id", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_trades_security_id", table_name="trades")
    op.drop_index("ix_trades_order_id", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_orders_placed_at", table_name="orders")
    op.drop_index("ix_orders_security_status", table_name="orders")
    op.drop_table("orders")
