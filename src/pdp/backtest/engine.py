from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from pymongo import MongoClient
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.market.bars import BarClosed
from pdp.strategy.abc import Strategy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = structlog.get_logger()

# Context var to hold the current simulation time
_sim_time: ContextVar[datetime] = ContextVar("_sim_time")


class SimulatedClock:
    """Context manager that provides simulated time during backtest."""

    def __init__(self, current_time: datetime) -> None:
        self.current_time = current_time
        self.token: Any = None

    def __enter__(self) -> datetime:
        self.token = _sim_time.set(self.current_time)
        return self.current_time

    def __exit__(self, *args: Any) -> None:
        if self.token:
            _sim_time.reset(self.token)

    async def __aenter__(self) -> datetime:
        self.token = _sim_time.set(self.current_time)
        return self.current_time

    async def __aexit__(self, *args: Any) -> None:
        if self.token:
            _sim_time.reset(self.token)


def get_sim_time() -> datetime:
    """Get the current simulated time during backtest, or wall-clock time otherwise."""
    try:
        return _sim_time.get()
    except LookupError:
        return datetime.now(UTC)


@dataclass
class BacktestPosition:
    """Tracks an open position during backtest."""

    symbol: str
    quantity: int
    entry_price: Decimal
    entry_time: datetime
    metadata: dict = field(default_factory=dict)


@dataclass
class BacktestBar:
    """Bar loaded from MongoDB market_bars."""

    security_id: str
    timeframe: str
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    oi: int

    def to_bar_closed(self) -> BarClosed:
        """Convert to BarClosed event for strategy."""
        return BarClosed(
            security_id=self.security_id,
            timeframe=self.timeframe,
            bar_time=self.bar_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            oi=self.oi,
        )


class BacktestEngine:
    """Event-driven backtest engine that replays historical bars through a strategy."""

    def __init__(
        self,
        strategy: Strategy,
        strategy_id: str,
        from_date: datetime,
        to_date: datetime,
        mongo_client: MongoClient,
        session_maker: async_sessionmaker[AsyncSession],
        initial_equity: Decimal = Decimal("100000"),
        timeframes: list[str] | None = None,
        mongo_db_name: str = "pdp",
    ) -> None:
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.from_date = from_date
        self.to_date = to_date
        self.mongo_client = mongo_client
        self.mongo_db_name = mongo_db_name
        self.session_maker = session_maker
        self.initial_equity = initial_equity
        self.timeframes = timeframes or ["1m", "5m", "15m"]

        self.current_equity = initial_equity
        self.positions: dict[str, BacktestPosition] = {}
        self.trade_log: list[dict] = []
        self.daily_snapshots: dict[datetime, dict] = {}

        self._bars_processed = 0
        self._max_equity = initial_equity
        self._daily_start_equity = initial_equity
        self._indicator_engine: Any = None  # set via attach_indicator_engine()

    def attach_indicator_engine(self, engine: Any) -> None:
        """Wire in the indicator engine so each bar updates indicators before strategy dispatch."""
        self._indicator_engine = engine

    async def load_market_history(self) -> list[BacktestBar]:
        """Fetch historical bars from MongoDB market_bars collection."""
        db = self.mongo_client.get_database(self.mongo_db_name)
        collection = db.get_collection("market_bars")

        # Bars are stored with ts + metadata.{security_id, timeframe} schema
        query = {
            "ts": {
                "$gte": self.from_date,
                "$lte": self.to_date,
            }
        }

        bars = list(collection.find(query).sort("ts", 1))
        log.info(
            "loaded_market_history",
            from_date=self.from_date.isoformat(),
            to_date=self.to_date.isoformat(),
            bars_count=len(bars),
        )

        return [
            BacktestBar(
                security_id=bar["metadata"]["security_id"],
                timeframe=bar["metadata"]["timeframe"],
                bar_time=bar["ts"],
                open=Decimal(str(bar["open"])),
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                close=Decimal(str(bar["close"])),
                volume=bar.get("volume", 0),
                oi=bar.get("oi", 0),
            )
            for bar in bars
        ]

    async def run(self) -> None:
        """Run the backtest event loop."""
        bars = await self.load_market_history()

        if not bars:
            log.warning(
                "no_bars_found",
                from_date=self.from_date.isoformat(),
                to_date=self.to_date.isoformat(),
            )
            return

        # Group bars by date for daily snapshots
        bars_by_date: dict[datetime, list[BacktestBar]] = {}
        for bar in bars:
            date_key = bar.bar_time.replace(hour=0, minute=0, second=0, microsecond=0)
            if date_key not in bars_by_date:
                bars_by_date[date_key] = []
            bars_by_date[date_key].append(bar)

        for date_key in sorted(bars_by_date.keys()):
            self._daily_start_equity = self.current_equity
            daily_bars = bars_by_date[date_key]

            for bar in daily_bars:
                await self._process_bar(bar)

            await self._record_daily_snapshot(date_key)

        log.info(
            "backtest_complete",
            strategy_id=self.strategy_id,
            bars_processed=self._bars_processed,
            trades_executed=len(self.trade_log),
            final_equity=float(self.current_equity),
        )

    async def _process_bar(self, bar: BacktestBar) -> None:
        """Process a single bar: update indicator engine then call strategy hook."""
        async with SimulatedClock(bar.bar_time):
            bar_closed = bar.to_bar_closed()
            # Update universal indicators before dispatching to the strategy so
            # ctx.indicators.supertrend() returns the value for the current bar.
            if self._indicator_engine is not None:
                self._indicator_engine.on_bar(bar_closed)
            await self.strategy.on_bar(bar_closed)
            self._bars_processed += 1

    async def _record_daily_snapshot(self, date_key: datetime) -> None:
        """Record daily equity snapshot."""
        daily_pnl = self.current_equity - self._daily_start_equity
        self.daily_snapshots[date_key] = {
            "date": date_key,
            "starting_equity": self._daily_start_equity,
            "ending_equity": self.current_equity,
            "daily_pnl": daily_pnl,
            "trades_count": len([t for t in self.trade_log if t["exit_time"].date() == date_key.date()]),
            "max_drawdown": await self._calculate_max_drawdown(),
            "current_drawdown_pct": await self._calculate_current_drawdown_pct(),
        }

    async def _calculate_max_drawdown(self) -> Decimal:
        """Calculate max drawdown from peak equity."""
        if self._max_equity == 0:
            return Decimal("0")
        return Decimal(str((self._max_equity - self.current_equity) / self._max_equity * 100))

    async def _calculate_current_drawdown_pct(self) -> Decimal:
        """Calculate current drawdown percentage from peak."""
        if self._max_equity == 0:
            return Decimal("0")
        return Decimal(str((self._max_equity - self.current_equity) / self._max_equity * 100))

    async def execute_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        current_price: Decimal,
        metadata: dict | None = None,
    ) -> bool:
        """Simulate market order execution at current bar close."""
        if side.upper() == "BUY":
            cost = Decimal(str(quantity)) * current_price
            if cost > self.current_equity:
                log.warning(
                    "order_rejected_insufficient_equity",
                    symbol=symbol,
                    quantity=quantity,
                    cost=float(cost),
                )
                return False

            self.positions[symbol] = BacktestPosition(
                symbol=symbol,
                quantity=quantity,
                entry_price=current_price,
                entry_time=datetime.now(UTC),
                metadata=metadata or {},
            )
            self.current_equity -= cost
            log.info("order_filled", symbol=symbol, side="BUY", quantity=quantity, price=float(current_price))
            return True

        elif side.upper() == "SELL":
            if symbol not in self.positions:
                log.warning("order_rejected_no_position", symbol=symbol)
                return False

            position = self.positions[symbol]
            if position.quantity != quantity:
                log.warning(
                    "order_rejected_qty_mismatch",
                    symbol=symbol,
                    position_qty=position.quantity,
                    order_qty=quantity,
                )
                return False

            proceeds = Decimal(str(quantity)) * current_price
            pnl = proceeds - (position.quantity * position.entry_price)

            self.trade_log.append({
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": float(position.entry_price),
                "entry_time": position.entry_time,
                "exit_price": float(current_price),
                "exit_time": datetime.now(UTC),
                "realized_pnl": float(pnl),
            })

            self.current_equity += proceeds
            self._max_equity = max(self._max_equity, self.current_equity)

            del self.positions[symbol]
            log.info("order_filled", symbol=symbol, side="SELL", quantity=quantity, price=float(current_price))
            return True

        return False
