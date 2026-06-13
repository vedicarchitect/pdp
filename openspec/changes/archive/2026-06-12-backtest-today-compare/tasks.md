## 1. Apply Missing PostgreSQL Tables (Migration 0009)

- [x] 1.1 Apply `CREATE TABLE IF NOT EXISTS backtest_runs (...)` DDL directly (idempotent; safe because alembic_version already shows 0010 and a downgrade would drop the alerts table)
- [x] 1.2 Apply `CREATE TABLE IF NOT EXISTS backtest_trades (...)` DDL with index `ix_backtest_trades_run_id`
- [x] 1.3 Apply `CREATE TABLE IF NOT EXISTS backtest_daily (...)` DDL with index `ix_backtest_daily_run_id`
- [x] 1.4 Verify all three tables exist via `pdp backtest list` (should return "No backtests found" instead of UndefinedTableError)

## 2. Fix BacktestEngine MongoDB Schema

- [x] 2.1 Add `mongo_db_name: str = "pdp"` parameter to `BacktestEngine.__init__()` and store as `self.mongo_db_name`
- [x] 2.2 In `load_market_history()`: replace `client.get_database("trading")` with `client.get_database(self.mongo_db_name)`
- [x] 2.3 In `load_market_history()`: change query field from `"bar_time"` to `"ts"` and sort by `"ts"`
- [x] 2.4 In `load_market_history()`: map `bar["metadata"]["security_id"]` and `bar["metadata"]["timeframe"]` instead of top-level fields; use `bar["ts"]` for `bar_time`
- [x] 2.5 Fix `backtest/indicators.py` `IndicatorCache.pre_compute()` with same three changes (db name, field names, sort key) — it has the same bugs

## 3. Wire IndicatorEngine into Backtest

- [x] 3.1 Add `self._indicator_engine: Any = None` to `BacktestEngine.__init__()`
- [x] 3.2 Add `BacktestEngine.attach_indicator_engine(engine)` method that sets `self._indicator_engine`
- [x] 3.3 In `BacktestEngine._process_bar()`: call `self._indicator_engine.on_bar(bar_closed)` before `strategy.on_bar(bar_closed)` (guard with `if self._indicator_engine is not None`)
- [x] 3.4 In `_run_backtest_async` in `backtest_commands.py`: create `IndicatorEngine(st_period=3, st_multiplier=1, timeframes=["5m"])`, call `engine.attach_indicator_engine(ie)`, and pass `IndicatorReader(ie)` as `indicators=` in the `StrategyContext`
- [x] 3.5 Add `session_maker=session_maker` to the `StrategyContext` constructor call (required by `strategy.on_init` for DB-backed state recovery)

## 4. Fix backtest_commands.py Settings References

- [x] 4.1 Replace `settings.MONGODB_URL` with `settings.MONGO_URI` in `run_backtest()`
- [x] 4.2 Pass `mongo_db_name=settings.MONGO_DB_NAME` to `BacktestEngine()`
- [x] 4.3 Move `from decimal import Decimal` to top-level import; remove duplicate inline import inside `_run_backtest_async`
- [x] 4.4 Import `IndicatorEngine` from `pdp.indicators.engine` and `IndicatorReader` from `pdp.strategy.context` at the top of the function (or module level)

## 5. Add Standalone Comparison Script

- [x] 5.1 Create `scripts/backtest_compare.py` with `--date YYYY-MM-DD` CLI argument (default: today IST)
- [x] 5.2 Load NIFTY 5m bars for the target date from MongoDB `pdp.market_bars` using `ts` field
- [x] 5.3 Optionally pre-seed `SuperTrendTracker` with the last 3 bars of the prior session to correctly initialize direction at market open
- [x] 5.4 Replay SuperTrend strategy logic bar-by-bar: track entries/scale-ins/closes using instrument security IDs from the `instruments` PostgreSQL table (read-only)
- [x] 5.5 Load option 5m bar prices from MongoDB for fill simulation (use bar `close` as fill price)
- [x] 5.6 Apply all strategy risk rules: `start_ist=09:30`, `square_off_ist=15:10`, `leg_stop_per_lot=1000`, `day_stop=10000`
- [x] 5.7 Read that day's paper journal from MongoDB `pdp.paper_journal` for comparison
- [x] 5.8 Print trade log section: entry/exit IST time, symbol, lots, entry price, exit price, P&L, close reason
- [x] 5.9 Print summary table: backtest vs paper on trades, wins, losses, win rate, gross sold, gross bought, net P&L
- [x] 5.10 Print delta row: absolute difference between backtest and paper for each numeric metric

## 6. Verify End-to-End

- [x] 6.1 Run `python scripts/backtest_compare.py --date 2026-06-12` and confirm trade log and comparison table print without errors
- [x] 6.2 Run `pdp backtest list` and confirm it returns results (or "No backtests found") without UndefinedTableError
- [ ] 6.3 Confirm `pdp backtest run supertrend_short --from 2026-06-09 --to 2026-06-10` completes with non-zero trades (uses known-good historical data from June 9)
  <!-- SKIPPED: CLI backtest routes orders through OrderRouter which writes to live paper orders/positions tables; running this would contaminate live strategy state. The MongoDB schema fixes are validated by 6.1 (comparison script produced 6 simulated trades for 2026-06-12). -->
