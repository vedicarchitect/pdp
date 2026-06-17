from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import click
import structlog
from pymongo import MongoClient
from sqlalchemy import select

from pdp.backtest.engine import BacktestEngine
from pdp.backtest.output import BacktestOutputWriter
from pdp.db.session import get_session_maker
from pdp.settings import get_settings
from pdp.strategy.registry import get_strategy

log = structlog.get_logger()


@click.group()
def backtest() -> None:
    """Backtest command group."""


@backtest.command("run")
@click.argument("strategy_id")
@click.option("--from", "from_date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--to", "to_date", required=True, help="End date (YYYY-MM-DD)")
@click.option("--initial-equity", default=100000, type=float, help="Starting equity (default: 100000)")
def run_backtest(
    strategy_id: str,
    from_date: str,
    to_date: str,
    initial_equity: float,
) -> None:
    """Run a backtest for a given strategy."""
    try:
        # Parse dates
        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(to_date, "%Y-%m-%d")

        if from_dt >= to_dt:
            click.echo("Error: from_date must be before to_date", err=True)
            return

        log.info(
            "backtest_start",
            strategy_id=strategy_id,
            from_date=from_date,
            to_date=to_date,
            initial_equity=initial_equity,
        )

        # Get strategy instance
        try:
            strategy = get_strategy(strategy_id)
            if not strategy:
                click.echo(f"Error: Strategy '{strategy_id}' not found", err=True)
                return
        except Exception as e:
            click.echo(f"Error loading strategy: {e}", err=True)
            return

        # Get settings and clients
        settings = get_settings()
        session_maker = get_session_maker()
        mongo_client = MongoClient(settings.MONGO_URI)

        # Create engine
        engine = BacktestEngine(
            strategy=strategy,
            strategy_id=strategy_id,
            from_date=from_dt,
            to_date=to_dt,
            mongo_client=mongo_client,
            session_maker=session_maker,
            initial_equity=Decimal(str(initial_equity)),
            mongo_db_name=settings.MONGO_DB_NAME,
        )

        import asyncio

        asyncio.run(_run_backtest_async(engine, session_maker))

    except ValueError as e:
        click.echo(f"Error: Invalid date format. Use YYYY-MM-DD: {e}", err=True)
    except Exception as e:
        log.error("backtest_error", error=str(e), exc_info=True)
        click.echo(f"Error running backtest: {e}", err=True)


async def _run_backtest_async(engine: BacktestEngine, session_maker) -> None:
    """Run backtest asynchronously."""
    try:
        from pdp.indicators.engine import IndicatorEngine
        from pdp.orders.router import OrderRouter
        from pdp.strategy.context import IndicatorReader, StrategyContext, StrategyOrderClient

        # Create indicator engine and attach it so bars update it before strategy dispatch.
        indicator_engine = IndicatorEngine(st_period=3, st_multiplier=1, timeframes=["5m"])
        engine.attach_indicator_engine(indicator_engine)

        async with session_maker() as session:
            # Create strategy context
            order_router = OrderRouter(session)
            orders_client = StrategyOrderClient(
                strategy_id=engine.strategy_id,
                order_router=order_router,
                session_maker=session_maker,
                max_open_orders=10,
                max_daily_loss_inr=50000,
            )

            ctx = StrategyContext(
                orders=orders_client,
                params=engine.strategy.params,
                watchlist=[],
                indicators=IndicatorReader(indicator_engine),
                session_maker=session_maker,
            )

            await engine.strategy.on_init(ctx)

            # Run the backtest
            await engine.run()

            # Write results
            output_writer = BacktestOutputWriter(engine, session)
            run_id = await output_writer.write_results()

            # Print summary
            total_return = (
                ((engine.current_equity - engine.initial_equity) / engine.initial_equity * 100)
                if engine.initial_equity > 0
                else 0
            )

            click.echo("\nBacktest Complete!")
            click.echo(f"Strategy: {engine.strategy_id}")
            click.echo(f"Period: {engine.from_date.date()} to {engine.to_date.date()}")
            click.echo(f"Initial Equity: ${float(engine.initial_equity):,.2f}")
            click.echo(f"Final Equity: ${float(engine.current_equity):,.2f}")
            click.echo(f"Total Return: {total_return:.2f}%")
            click.echo(f"Total Trades: {len(engine.trade_log)}")
            click.echo(f"Bars Processed: {engine._bars_processed}")
            click.echo(f"Run ID: {run_id}")
            click.echo(f"Results: backtest/results/{run_id}/")

            await engine.strategy.on_shutdown()

    except Exception as e:
        log.error("backtest_async_error", error=str(e), exc_info=True)
        raise


@backtest.command("list")
@click.option("--strategy-id", help="Filter by strategy ID")
@click.option("--limit", default=10, type=int, help="Number of results (default: 10)")
def list_backtests(strategy_id: str | None, limit: int) -> None:
    """List recent backtests."""


    try:
        session_maker = get_session_maker()

        import asyncio

        asyncio.run(_list_backtests_async(session_maker, strategy_id, limit))

    except Exception as e:
        log.error("list_backtests_error", error=str(e))
        click.echo(f"Error listing backtests: {e}", err=True)


async def _list_backtests_async(session_maker, strategy_id: str | None, limit: int) -> None:
    """List backtests asynchronously."""
    from sqlalchemy import desc

    from pdp.backtest.models import BacktestRun

    async with session_maker() as session:
        stmt = select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)

        if strategy_id:
            stmt = stmt.where(BacktestRun.strategy_id == strategy_id)

        result = await session.execute(stmt)
        runs = result.scalars().all()

        if not runs:
            click.echo("No backtests found")
            return

        click.echo(f"\nBacktests (showing {len(runs)}):\n")
        for run in runs:
            total_return = (
                ((run.end_equity - run.start_equity) / run.start_equity * 100)
                if run.start_equity > 0
                else 0
            )
            click.echo(f"ID: {run.id}")
            click.echo(f"  Strategy: {run.strategy_id}")
            click.echo(f"  Period: {run.from_date.date()} to {run.to_date.date()}")
            click.echo(f"  Return: {total_return:.2f}%")
            click.echo(f"  Trades: {run.total_trades}")
            click.echo(f"  Created: {run.created_at}")
            click.echo()
