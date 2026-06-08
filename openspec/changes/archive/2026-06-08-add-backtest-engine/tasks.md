## 1. Database Schema Setup

- [x] 1.1 Create PostgreSQL `backtest_runs` table (strategy_id, from_date, to_date, start_equity, end_equity, total_trades, config_json, created_at)
- [x] 1.2 Create PostgreSQL `backtest_trades` table (backtest_run_id, symbol, quantity, entry_price, exit_price, entry_timestamp, exit_timestamp, realized_pnl, strategy_metadata)
- [x] 1.3 Create PostgreSQL `backtest_daily` table (backtest_run_id, date, starting_equity, ending_equity, daily_pnl, trades_count, max_drawdown, current_drawdown_pct)
- [x] 1.4 Add indexes on (backtest_run_id, strategy_id, created_at) for query performance
- [x] 1.5 Create local `backtest/results/` directory structure for CSV exports

## 2. Backtest Engine Core Architecture

- [x] 2.1 Create `pdp/backtest/engine.py` with `BacktestEngine` class and initialization logic
- [x] 2.2 Implement `BacktestEngine.load_market_history()` to fetch bars from MongoDB market_bars
- [x] 2.3 Implement event loop: `BacktestEngine.run()` that processes bars chronologically
- [x] 2.4 Create `SimulatedClock` context that feeds `datetime.now()` to strategy
- [x] 2.5 Implement bar/tick event dispatch to strategy hooks (on_bar, on_tick)
- [x] 2.6 Add position and trade tracking to engine state

## 3. Indicator Pre-computation

- [x] 3.1 Create `pdp/backtest/indicators.py` with `IndicatorCache` class
- [x] 3.2 Implement Polars vectorized computation for each indicator (SMA, EMA, RSI, VWAP, etc.)
- [x] 3.3 Add `IndicatorCache.pre_compute(security, timeframe, from_date, to_date)` method
- [x] 3.4 Implement in-memory caching and lookup by timestamp
- [x] 3.5 Validate indicator coverage: error if strategy requires unmappable indicator
- [x] 3.6 Add optional Redis backing for large backtests (memory optimization)

## 4. Order Execution Simulation

- [x] 4.1 Create `pdp/backtest/execution.py` with `BacktestExecutor` class
- [x] 4.2 Implement market order fill simulation at bar close (OHLC)
- [x] 4.3 Implement position limit validation and order rejection
- [x] 4.4 Add trade creation and P&L calculation
- [x] 4.5 Implement order rejection event dispatch to strategy
- [x] 4.6 Add commissions/fees model (initially zero, extensible)

## 5. CLI Command Implementation

- [x] 5.1 Add `backtest` subcommand to main CLI entry point
- [x] 5.2 Implement `pdp backtest run` command with argparse (--from, --to required)
- [x] 5.3 Add argument validation (date range, strategy_id existence)
- [x] 5.4 Implement progress reporting during backtest execution
- [x] 5.5 Add error handling and user-friendly error messages
- [x] 5.6 Connect to database and create backtest_run record before processing

## 6. Output & Persistence

- [x] 6.1 Create `pdp/backtest/output.py` with `BacktestOutputWriter` class
- [x] 6.2 Implement trade recording to `backtest_trades` table
- [x] 6.3 Implement daily equity snapshot calculation and storage
- [x] 6.4 Implement CSV export to `backtest/results/<run_id>/trades.csv`
- [x] 6.5 Implement CSV export to `backtest/results/<run_id>/daily.csv`
- [x] 6.6 Add equity curve and drawdown metrics to daily snapshots
- [x] 6.7 Store strategy configuration snapshot as JSON in backtest_runs

## 7. Query & Reporting API

- [x] 7.1 Add REST endpoint `GET /api/backtests` to list backtest_runs
- [x] 7.2 Implement filtering by strategy_id, from_date, to_date
- [x] 7.3 Add endpoint `GET /api/backtests/<run_id>` to fetch run details
- [x] 7.4 Add endpoint `GET /api/backtests/<run_id>/trades` to fetch trade list
- [x] 7.5 Add endpoint `GET /api/backtests/<run_id>/daily` to fetch daily curves
- [x] 7.6 Implement sorting and pagination for large result sets

## 8. Testing & Validation

- [x] 8.1 Write unit tests for `IndicatorCache` pre-computation
- [x] 8.2 Write integration test for backtest end-to-end (sample strategy)
- [x] 8.3 Validate equity curve calculation against sample trades
- [x] 8.4 Test date range validation and gap handling
- [x] 8.5 Test order rejection scenarios and P&L edge cases
- [x] 8.6 Verify CSV export format and readability
- [x] 8.7 Load test with 5+ year history backtest

## 9. Documentation & Rollout

- [x] 9.1 Add backtest architecture to ARCHITECTURE.md
- [x] 9.2 Write user guide: `docs/backtest.md` with CLI examples
- [x] 9.3 Document indicator pre-computation assumptions
- [x] 9.4 Document order execution model and fill assumptions
- [x] 9.5 Archive change via `openspec archive add-backtest-engine`
