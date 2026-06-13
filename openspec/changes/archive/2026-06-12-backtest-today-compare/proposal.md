## Why

The backtest engine has three silent bugs that cause it to produce zero trades on every run: it
reads from a non-existent MongoDB database (`trading` instead of `pdp`), uses the wrong field
names for the time-series bar schema (`bar_time`/`security_id` vs `ts`/`metadata.security_id`),
and never feeds bars to the IndicatorEngine before dispatching them to the strategy, so
`ctx.indicators.supertrend()` always returns `None` and the strategy short-circuits immediately.
Additionally, the `backtest_runs` table is missing from PostgreSQL because migration 0009 was
silently skipped when the DB was previously at a state where 0010 applied directly after 0008.
These bugs make it impossible to run any backtest or compare simulated vs live paper results.

## What Changes

- Fix `BacktestEngine.load_market_history()`: use `settings.MONGO_DB_NAME` (passed in as
  `mongo_db_name`), query field `ts` instead of `bar_time`, and map `metadata.security_id` /
  `metadata.timeframe` instead of top-level fields.
- Fix `BacktestEngine._process_bar()`: call `indicator_engine.on_bar(bar_closed)` before
  `strategy.on_bar(bar_closed)` so SuperTrend state is up-to-date when the strategy reads it.
- Add `BacktestEngine.attach_indicator_engine()` method and wire an `IndicatorEngine` into the
  `StrategyContext` via `IndicatorReader` inside `_run_backtest_async`.
- Fix `backtest_commands.py`: use `settings.MONGO_URI` (not `settings.MONGODB_URL`) and pass
  `mongo_db_name=settings.MONGO_DB_NAME` to the engine.
- Apply missing migration 0009 tables (`backtest_runs`, `backtest_trades`, `backtest_daily`)
  directly via DDL since alembic cannot re-run them without downgrading past active data.
- Add `scripts/backtest_compare.py`: standalone script that loads today's NIFTY 5m bars and
  option bars from MongoDB, replays SuperTrend strategy logic without touching the live
  PostgreSQL orders tables, and prints a side-by-side paper vs backtest comparison.

## Capabilities

### New Capabilities
- `backtest-compare`: Standalone paper-vs-backtest comparison script that replays the
  SuperTrend strategy on historical MongoDB bars and reports simulated P&L alongside the
  live paper journal stats for the same day.

### Modified Capabilities
- `backtest`: Fix MongoDB schema mismatch, missing IndicatorEngine wiring, and missing
  `backtest_runs` table so the CLI `pdp backtest run` command executes correctly end-to-end.

## Impact

- `src/pdp/backtest/engine.py` — MongoDB db name, field names, IndicatorEngine dispatch
- `src/pdp/cli/backtest_commands.py` — settings attribute names, IndicatorEngine wiring
- PostgreSQL schema — `backtest_runs`, `backtest_trades`, `backtest_daily` tables added
- New file: `scripts/backtest_compare.py`
