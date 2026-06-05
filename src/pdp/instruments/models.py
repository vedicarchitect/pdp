from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pdp.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("security_id", "exchange_segment", name="uq_instruments_secid_seg"),
        Index("ix_instruments_trading_symbol", "trading_symbol"),
        Index("ix_instruments_underlying_expiry", "underlying", "expiry"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[str] = mapped_column(String, nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String, nullable=False)
    trading_symbol: Mapped[str] = mapped_column(String, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String, nullable=False)
    underlying: Mapped[str | None] = mapped_column(String, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.05"))
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
