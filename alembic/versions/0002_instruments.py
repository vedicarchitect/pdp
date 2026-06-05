"""instruments

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column("trading_symbol", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("strike", sa.Numeric(12, 2), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tick_size", sa.Numeric(8, 4), nullable=False, server_default="0.05"),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("security_id", "exchange_segment", name="uq_instruments_secid_seg"),
    )
    op.create_index("ix_instruments_trading_symbol", "instruments", ["trading_symbol"])
    op.create_index(
        "ix_instruments_underlying_expiry", "instruments", ["underlying", "expiry"]
    )


def downgrade() -> None:
    op.drop_index("ix_instruments_underlying_expiry", table_name="instruments")
    op.drop_index("ix_instruments_trading_symbol", table_name="instruments")
    op.drop_table("instruments")
