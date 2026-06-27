"""subscriptions

Revision ID: 0004
Revises: 0002
Create Date: 2026-06-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("exchange_segment", sa.String(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("security_id", "exchange_segment", name="uq_subscriptions_secid_seg"),
    )
    op.create_index("ix_subscriptions_security_id", "subscriptions", ["security_id"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_security_id", table_name="subscriptions")
    op.drop_table("subscriptions")
