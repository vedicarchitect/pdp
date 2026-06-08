"""alerts table

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-08

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("security_id", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("threshold", sa.Numeric(18, 6), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False, server_default="[\"WS\"]"),
        sa.Column("status", sa.String(), nullable=False, server_default="ARMED"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_alerts_user_status", "alerts", ["user_id", "status"])
    op.create_index("ix_alerts_security_condition", "alerts", ["security_id", "condition"])
    op.create_unique_constraint(
        "uq_alerts_user_sec_cond_thresh",
        "alerts",
        ["user_id", "security_id", "condition", "threshold"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_alerts_user_sec_cond_thresh", "alerts", type_="unique")
    op.drop_index("ix_alerts_security_condition", table_name="alerts")
    op.drop_index("ix_alerts_user_status", table_name="alerts")
    op.drop_table("alerts")
