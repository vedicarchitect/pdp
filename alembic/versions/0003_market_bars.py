"""market_bars table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_bars",
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(4), nullable=False),
        sa.Column("bar_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("oi", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("security_id", "timeframe", "bar_time"),
    )
    op.create_index(
        "ix_market_bars_security_tf_time",
        "market_bars",
        ["security_id", "timeframe", "bar_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_bars_security_tf_time", table_name="market_bars")
    op.drop_table("market_bars")
