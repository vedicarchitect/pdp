"""positions: add strategy_id column, rekeyed unique constraint

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-18

Fixes the shared-position bug: positions were keyed by (security_id, exchange_segment,
product) alone, so two strategies trading the same strike shared one Position row.
Now keyed by (strategy_id, security_id, exchange_segment, product).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "761f630d68d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add strategy_id column (nullable — existing rows keep NULL)
    op.add_column(
        "positions",
        sa.Column("strategy_id", sa.String(), nullable=True),
    )
    op.create_index("ix_positions_strategy_id", "positions", ["strategy_id"])

    # Drop the old unique constraint
    op.drop_constraint("uq_positions_sid_seg_product", "positions", type_="unique")

    # Add the new composite unique constraint that includes strategy_id.
    # PostgreSQL treats two NULLs as distinct in unique indexes, so rows with
    # strategy_id=NULL do not conflict with each other.
    op.create_unique_constraint(
        "uq_positions_strategy_sid_seg_product",
        "positions",
        ["strategy_id", "security_id", "exchange_segment", "product"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_positions_strategy_sid_seg_product", "positions", type_="unique")
    op.drop_index("ix_positions_strategy_id", table_name="positions")
    op.drop_column("positions", "strategy_id")
    op.create_unique_constraint(
        "uq_positions_sid_seg_product",
        "positions",
        ["security_id", "exchange_segment", "product"],
    )
