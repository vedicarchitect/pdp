"""dhan_broker — orders.broker_order_id + dhan broker_costs rows

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None

# Dhan live cost rows — modelled on published NSE/BSE charge schedules.
# Best-effort; reconciled against broker contract notes later (see design.md).
# Columns: instrument_type, brokerage_bps, brokerage_flat, stt_bps,
#          exchange_fee_bps, gst_pct, sebi_charges_bps, stamp_duty_bps
_DHAN_DEFAULTS = [
    ("EQUITY",   0,    20, 1.0,  0.0325, 18, 0.0001, 0.015),
    ("FUTIDX",   0,    20, 1.0,  0.0500, 18, 0.0001, 0.002),
    ("OPTIDX",   0,    20, 0.05, 0.5300, 18, 0.0001, 0.003),
    ("FUTSTK",   0,    20, 1.0,  0.0500, 18, 0.0001, 0.002),
    ("OPTSTK",   0,    20, 0.05, 0.5300, 18, 0.0001, 0.003),
]


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_orders_broker_order_id", "orders", ["broker_order_id"], unique=False
    )

    broker_costs = sa.table(
        "broker_costs",
        sa.column("broker", sa.String()),
        sa.column("instrument_type", sa.String()),
        sa.column("brokerage_bps", sa.Numeric()),
        sa.column("brokerage_flat", sa.Numeric()),
        sa.column("stt_bps", sa.Numeric()),
        sa.column("exchange_fee_bps", sa.Numeric()),
        sa.column("gst_pct", sa.Numeric()),
        sa.column("sebi_charges_bps", sa.Numeric()),
        sa.column("stamp_duty_bps", sa.Numeric()),
    )
    op.bulk_insert(
        broker_costs,
        [
            {
                "broker": "dhan",
                "instrument_type": row[0],
                "brokerage_bps": row[1],
                "brokerage_flat": row[2],
                "stt_bps": row[3],
                "exchange_fee_bps": row[4],
                "gst_pct": row[5],
                "sebi_charges_bps": row[6],
                "stamp_duty_bps": row[7],
            }
            for row in _DHAN_DEFAULTS
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM broker_costs WHERE broker = 'dhan'")
    op.drop_index("ix_orders_broker_order_id", table_name="orders")
    op.drop_column("orders", "broker_order_id")
