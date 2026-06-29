"""broker-order-safety: add freeze_qty to instruments

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("freeze_qty", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("instruments", "freeze_qty")
