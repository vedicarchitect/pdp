## MODIFIED Requirements

### Requirement: Historical bar replay
The system SHALL replay historical market bars in chronological order, feeding them to the
strategy via the same event-driven interface as live trading. Source bars SHALL be fetched from
the MongoDB `market_bars` collection using the `ts` field for time filtering and
`metadata.security_id` / `metadata.timeframe` for instrument identification (matching the schema
written by `BarWriter`). The MongoDB database name SHALL be read from `settings.MONGO_DB_NAME`
and SHALL NOT be hard-coded. Resampling from 1-minute bars to the signal timeframe is specified
separately and remains pre-existing tech debt outside the scope of this change.

#### Scenario: Bars arrive in correct order
- **WHEN** backtest processes historical bars for a security between two dates
- **THEN** bars are processed in ascending `ts` order, one at a time

#### Scenario: MongoDB schema fields are mapped correctly
- **WHEN** the backtest engine loads bars from MongoDB
- **THEN** it queries the `ts` field for date range and reads `metadata.security_id` and
  `metadata.timeframe` for instrument identification (not top-level `bar_time`, `security_id`,
  or `timeframe`)

#### Scenario: Database name from settings
- **WHEN** the backtest engine connects to MongoDB
- **THEN** it uses the database name from `settings.MONGO_DB_NAME` (default `pdp`), not a
  hard-coded string

#### Scenario: On-bar hook is invoked
- **WHEN** a bar is produced during replay
- **THEN** the strategy's `on_bar()` hook is called with that bar

#### Scenario: Missing bars in history
- **WHEN** backtest encounters a gap in bar history
- **THEN** the system logs a warning with the gap period and continues processing

---

### Requirement: Pre-computed indicator access
The system SHALL update the live `IndicatorEngine` on each bar before dispatching the bar to
the strategy, so `ctx.indicators.supertrend()` returns the value computed for the current bar
when `strategy.on_bar()` executes. A fresh `IndicatorEngine(st_period=3, st_multiplier=1)`
SHALL be created per backtest run and attached to both the `BacktestEngine` (for bar-by-bar
updates) and the `StrategyContext` (via `IndicatorReader`) so the strategy's indicator reads
during replay are identical to live trading behaviour.

#### Scenario: IndicatorEngine updated before strategy dispatch
- **WHEN** the backtest engine processes each bar
- **THEN** `indicator_engine.on_bar(bar_closed)` is called before `strategy.on_bar(bar_closed)`

#### Scenario: Strategy accesses indicator during replay
- **WHEN** strategy calls `ctx.indicators.supertrend(security_id, timeframe)` inside `on_bar()`
- **THEN** system returns the SuperTrend state computed for the current bar (not None)

#### Scenario: IndicatorReader is wired into StrategyContext
- **WHEN** `_run_backtest_async` builds the StrategyContext
- **THEN** `ctx.indicators` is an `IndicatorReader` wrapping the same `IndicatorEngine`
  attached to the `BacktestEngine`

---

### Requirement: Backtest run metadata
The system SHALL create a `backtest_runs` table row for each backtest with strategy_id, date
range, start/end equity, total trades, and configuration snapshot. The table SHALL exist in
PostgreSQL before any backtest is run; if missing it SHALL be created via idempotent DDL
(`CREATE TABLE IF NOT EXISTS`) rather than requiring a full alembic migration replay.

#### Scenario: Backtest run is recorded
- **WHEN** backtest completes
- **THEN** a record is inserted into `backtest_runs` with strategy_id, from_date, to_date,
  start_equity, end_equity

#### Scenario: Configuration snapshot is stored
- **WHEN** backtest run is recorded
- **THEN** `backtest_runs` includes a JSON column with strategy config at backtest time

#### Scenario: Table missing does not crash at startup
- **WHEN** `backtest_runs` does not exist and `pdp backtest list` is called
- **THEN** system returns a clear error rather than an unhandled exception
