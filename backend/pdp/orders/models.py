from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pdp.db.base import Base


@dataclass
class PreflightResult:
    ok: bool = True
    margin_required: Decimal = Decimal("0")
    margin_available: Decimal = Decimal("0")
    charge_estimate: Decimal = Decimal("0")
    violations: list[str] = field(default_factory=list)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL_M"


class OrderStatus(StrEnum):
    NEW = "NEW"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Product(StrEnum):
    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"
    NRML = "NRML"
    MIS = "MIS"


class TradeMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    broker: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    product: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=OrderStatus.NEW)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    strategy_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    charges: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "security_id", "exchange_segment", "product",
            name="uq_positions_strategy_sid_seg_product",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String, nullable=False)
    product: Mapped[str] = mapped_column(String, nullable=False)
    net_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerCost(Base):
    __tablename__ = "broker_costs"

    broker: Mapped[str] = mapped_column(String, primary_key=True)
    instrument_type: Mapped[str] = mapped_column(String, primary_key=True)
    brokerage_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    brokerage_flat: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    stt_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    exchange_fee_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    gst_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("18"))
    sebi_charges_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    stamp_duty_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
