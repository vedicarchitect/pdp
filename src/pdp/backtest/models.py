from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from pdp.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint("id", name="uq_backtest_runs_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    from_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_equity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    end_equity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    strategy_metadata: Mapped[dict] = mapped_column(JSON, nullable=True)


class BacktestDaily(Base):
    __tablename__ = "backtest_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    ending_equity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    daily_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    current_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
