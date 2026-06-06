"""drop market_bars hypertable — bars moved to MongoDB

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-06

"""
from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_bars CASCADE")


def downgrade() -> None:
    # Intentionally no-op: hypertable recreation belongs to the
    # add-market-data-bars migration; this is a one-way move to MongoDB.
    pass
