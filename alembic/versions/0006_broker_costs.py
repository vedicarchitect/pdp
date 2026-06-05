"""broker_costs

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-05

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None

# Default paper cost rows (all bps values × trade_value/10000, flat in ₹)
# instrument_type matches instruments.instrument_type values from Dhan master
_PAPER_DEFAULTS = [
    # (instrument_type, brokerage_bps, brokerage_flat, stt_bps, exchange_fee_bps, gst_pct, sebi_charges_bps, stamp_duty_bps)
    ("EQUITY",   0,    20, 1.0,  0.0325, 18, 0.0001, 0.015),
    ("FUTIDX",   0,    20, 1.0,  0.0500, 18, 0.0001, 0.002),
    ("OPTIDX",   0,    20, 0.05, 0.5300, 18, 0.0001, 0.003),
    ("FUTSTK",   0,    20, 1.0,  0.0500, 18, 0.0001, 0.002),
    ("OPTSTK",   0,    20, 0.05, 0.5300, 18, 0.0001, 0.003),
]


def upgrade() -> None:
    t = op.create_table(
        "broker_costs",
        sa.Column("broker", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=False),
        sa.Column(
            "brokerage_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "brokerage_flat", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "stt_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "exchange_fee_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "gst_pct", sa.Numeric(8, 4), nullable=False, server_default="18"
        ),
        sa.Column(
            "sebi_charges_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "stamp_duty_bps", sa.Numeric(8, 4), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint("broker", "instrument_type"),
    )
    op.bulk_insert(
        t,
        [
            {
                "broker": "paper",
                "instrument_type": row[0],
                "brokerage_bps": row[1],
                "brokerage_flat": row[2],
                "stt_bps": row[3],
                "exchange_fee_bps": row[4],
                "gst_pct": row[5],
                "sebi_charges_bps": row[6],
                "stamp_duty_bps": row[7],
            }
            for row in _PAPER_DEFAULTS
        ],
    )


def downgrade() -> None:
    op.drop_table("broker_costs")
