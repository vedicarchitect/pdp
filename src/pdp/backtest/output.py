from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pdp.backtest.engine import BacktestEngine

log = structlog.get_logger()


class BacktestOutputWriter:
    """Handles persistence of backtest results to database and CSV."""

    def __init__(self, engine: BacktestEngine, session: AsyncSession) -> None:
        self.engine = engine
        self.session = session
        self.results_dir = Path("backtest/results")

    async def write_results(self) -> int:
        """Write all backtest results to database and files."""
        from pdp.backtest.models import BacktestDaily, BacktestRun, BacktestTrade

        # Create backtest run record
        run_record = {
            "strategy_id": self.engine.strategy_id,
            "from_date": self.engine.from_date,
            "to_date": self.engine.to_date,
            "start_equity": self.engine.initial_equity,
            "end_equity": self.engine.current_equity,
            "total_trades": len(self.engine.trade_log),
            "config_json": {
                "timeframes": self.engine.timeframes,
                "initial_equity": float(self.engine.initial_equity),
            },
        }

        stmt = insert(BacktestRun).values(**run_record)
        result = await self.session.execute(stmt)
        await self.session.commit()

        run_id = result.inserted_primary_key[0]
        log.info("backtest_run_created", run_id=run_id)

        # Write trade records
        await self._write_trades(run_id, BacktestTrade)

        # Write daily snapshots
        await self._write_daily_snapshots(run_id, BacktestDaily)

        # Export CSV files
        await self._export_csv(run_id)

        return run_id

    async def _write_trades(self, run_id: int, trade_model: type) -> None:
        """Write trade records to database."""
        if not self.engine.trade_log:
            return

        trade_records = []
        for trade in self.engine.trade_log:
            trade_records.append({
                "backtest_run_id": run_id,
                "symbol": trade["symbol"],
                "quantity": trade["quantity"],
                "entry_price": trade["entry_price"],
                "exit_price": trade["exit_price"],
                "entry_timestamp": trade["entry_time"],
                "exit_timestamp": trade["exit_time"],
                "realized_pnl": trade["realized_pnl"],
                "strategy_metadata": None,
            })

        stmt = insert(trade_model).values(trade_records)
        await self.session.execute(stmt)
        await self.session.commit()
        log.info("trades_written", run_id=run_id, count=len(trade_records))

    async def _write_daily_snapshots(self, run_id: int, daily_model: type) -> None:
        """Write daily equity snapshots to database."""
        if not self.engine.daily_snapshots:
            return

        daily_records = []
        for date_key, snapshot in self.engine.daily_snapshots.items():
            daily_records.append({
                "backtest_run_id": run_id,
                "date": snapshot["date"],
                "starting_equity": snapshot["starting_equity"],
                "ending_equity": snapshot["ending_equity"],
                "daily_pnl": snapshot["daily_pnl"],
                "trades_count": snapshot["trades_count"],
                "max_drawdown": snapshot["max_drawdown"],
                "current_drawdown_pct": snapshot["current_drawdown_pct"],
            })

        stmt = insert(daily_model).values(daily_records)
        await self.session.execute(stmt)
        await self.session.commit()
        log.info("daily_snapshots_written", run_id=run_id, count=len(daily_records))

    async def _export_csv(self, run_id: int) -> None:
        """Export backtest results to CSV files."""
        run_dir = self.results_dir / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        await self._export_trades_csv(run_dir)
        await self._export_daily_csv(run_dir)

        log.info("csv_export_complete", run_id=run_id, directory=str(run_dir))

    async def _export_trades_csv(self, run_dir: Path) -> None:
        """Export trade details to CSV."""
        csv_path = run_dir / "trades.csv"

        if not self.engine.trade_log:
            log.warning("no_trades_to_export")
            return

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "symbol",
                    "quantity",
                    "entry_price",
                    "entry_time",
                    "exit_price",
                    "exit_time",
                    "realized_pnl",
                    "return_pct",
                ],
            )
            writer.writeheader()

            for trade in self.engine.trade_log:
                entry_val = trade["quantity"] * trade["entry_price"]
                return_pct = (trade["realized_pnl"] / entry_val * 100) if entry_val > 0 else 0

                writer.writerow({
                    "symbol": trade["symbol"],
                    "quantity": trade["quantity"],
                    "entry_price": trade["entry_price"],
                    "entry_time": trade["entry_time"].isoformat(),
                    "exit_price": trade["exit_price"],
                    "exit_time": trade["exit_time"].isoformat(),
                    "realized_pnl": trade["realized_pnl"],
                    "return_pct": return_pct,
                })

        log.info("trades_csv_exported", path=str(csv_path), count=len(self.engine.trade_log))

    async def _export_daily_csv(self, run_dir: Path) -> None:
        """Export daily equity curve to CSV."""
        csv_path = run_dir / "daily.csv"

        if not self.engine.daily_snapshots:
            log.warning("no_daily_snapshots_to_export")
            return

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "date",
                    "starting_equity",
                    "ending_equity",
                    "daily_pnl",
                    "daily_return_pct",
                    "trades_count",
                    "max_drawdown",
                    "current_drawdown_pct",
                ],
            )
            writer.writeheader()

            for date_key in sorted(self.engine.daily_snapshots.keys()):
                snapshot = self.engine.daily_snapshots[date_key]
                daily_return = (
                    (snapshot["ending_equity"] - snapshot["starting_equity"]) / snapshot["starting_equity"] * 100
                    if snapshot["starting_equity"] > 0
                    else 0
                )

                writer.writerow({
                    "date": snapshot["date"].date().isoformat(),
                    "starting_equity": snapshot["starting_equity"],
                    "ending_equity": snapshot["ending_equity"],
                    "daily_pnl": snapshot["daily_pnl"],
                    "daily_return_pct": daily_return,
                    "trades_count": snapshot["trades_count"],
                    "max_drawdown": snapshot["max_drawdown"],
                    "current_drawdown_pct": snapshot["current_drawdown_pct"],
                })

        log.info(
            "daily_csv_exported",
            path=str(csv_path),
            count=len(self.engine.daily_snapshots),
        )
