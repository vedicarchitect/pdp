from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, desc, select

from pdp.backtest.models import BacktestDaily, BacktestRun, BacktestTrade
from pdp.backtest.options_replay import OptionsReplayEngine
from pdp.backtest.options_strategy import OptionsStrategyConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


@router.get("")
async def list_backtests(
    session: AsyncSession,
    strategy_id: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """List backtest runs with optional filtering."""
    stmt = select(BacktestRun).order_by(desc(BacktestRun.created_at))

    if strategy_id:
        stmt = stmt.where(BacktestRun.strategy_id == strategy_id)

    if from_date and to_date:
        stmt = stmt.where(
            and_(
                BacktestRun.from_date >= from_date,
                BacktestRun.to_date <= to_date,
            )
        )

    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    runs = result.scalars().all()

    return {
        "total": len(runs),
        "limit": limit,
        "offset": offset,
        "runs": [
            {
                "id": run.id,
                "strategy_id": run.strategy_id,
                "from_date": run.from_date.isoformat(),
                "to_date": run.to_date.isoformat(),
                "start_equity": float(run.start_equity),
                "end_equity": float(run.end_equity),
                "total_trades": run.total_trades,
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
        ],
    }


@router.get("/{run_id}")
async def get_backtest_run(
    run_id: int,
    session: AsyncSession,
) -> dict:
    """Get details for a specific backtest run."""
    stmt = select(BacktestRun).where(BacktestRun.id == run_id)
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    total_return = (
        ((run.end_equity - run.start_equity) / run.start_equity * 100)
        if run.start_equity > 0
        else 0
    )

    return {
        "id": run.id,
        "strategy_id": run.strategy_id,
        "from_date": run.from_date.isoformat(),
        "to_date": run.to_date.isoformat(),
        "start_equity": float(run.start_equity),
        "end_equity": float(run.end_equity),
        "total_return_pct": total_return,
        "total_trades": run.total_trades,
        "config": run.config_json,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/{run_id}/trades")
async def get_backtest_trades(
    run_id: int,
    session: AsyncSession,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Get trades for a specific backtest run."""
    stmt = (
        select(BacktestTrade)
        .where(BacktestTrade.backtest_run_id == run_id)
        .order_by(BacktestTrade.entry_timestamp)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    trades = result.scalars().all()

    return {
        "run_id": run_id,
        "limit": limit,
        "offset": offset,
        "total": len(trades),
        "trades": [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "quantity": trade.quantity,
                "entry_price": float(trade.entry_price),
                "exit_price": float(trade.exit_price),
                "entry_timestamp": trade.entry_timestamp.isoformat(),
                "exit_timestamp": trade.exit_timestamp.isoformat(),
                "realized_pnl": float(trade.realized_pnl),
            }
            for trade in trades
        ],
    }


@router.get("/{run_id}/daily")
async def get_backtest_daily(
    run_id: int,
    session: AsyncSession,
) -> dict:
    """Get daily equity curves for a backtest run."""
    stmt = (
        select(BacktestDaily)
        .where(BacktestDaily.backtest_run_id == run_id)
        .order_by(BacktestDaily.date)
    )
    result = await session.execute(stmt)
    dailies = result.scalars().all()

    return {
        "run_id": run_id,
        "daily_count": len(dailies),
        "daily": [
            {
                "date": daily.date.date().isoformat(),
                "starting_equity": float(daily.starting_equity),
                "ending_equity": float(daily.ending_equity),
                "daily_pnl": float(daily.daily_pnl),
                "trades_count": daily.trades_count,
                "max_drawdown": float(daily.max_drawdown),
                "current_drawdown_pct": float(daily.current_drawdown_pct),
            }
            for daily in dailies
        ],
    }


@router.post("/run")
async def run_backtest(request: Request, config: OptionsStrategyConfig) -> dict:
    """Run an options strategy backtest synchronously and return results.

    Date ranges exceeding 90 days are rejected; use the async job runner
    for large backtests once it supports this endpoint.
    """
    from_date: date = config.date_range.from_
    to_date: date = config.date_range.to
    delta_days = (to_date - from_date).days
    if delta_days > 90:
        raise HTTPException(
            status_code=400,
            detail="Date range exceeds 90 days. Use async job runner for large backtests.",
        )

    mongo_db = request.app.state.mongo_db
    engine = OptionsReplayEngine(mongo_db)
    result = engine.run(config)

    return {
        "config_name": result.config_name,
        "date_range": {
            "from": result.date_range[0].isoformat(),
            "to": result.date_range[1].isoformat(),
        },
        "summary": {
            "total_pnl": result.total_pnl,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "commissions_total": result.commissions_total,
        },
        "equity_curve": result.equity_curve,
        "daily_pnl": result.daily_pnl,
        "weekday_stats": result.weekday_stats,
        "trade_log": result.trade_log,
    }
