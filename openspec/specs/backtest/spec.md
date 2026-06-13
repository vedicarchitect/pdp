# backtest Specification

## Purpose
TBD - created by archiving change add-backtest-engine. Update Purpose after archive.
## Requirements
### Requirement: Backtest CLI invocation
The system SHALL provide a CLI command to run historical backtests against a specified strategy.

#### Scenario: Valid backtest command
- **WHEN** user runs `pdp backtest run <strategy_id> --from YYYY-MM-DD --to YYYY-MM-DD`
- **THEN** system initiates backtest, replays historical data, and returns backtest_run_id

#### Scenario: Missing required parameters
- **WHEN** user runs `pdp backtest run <strategy_id>` without `--from` and `--to`
- **THEN** system returns error with required parameters message

#### Scenario: Invalid date range
- **WHEN** user runs `pdp backtest run <strategy_id> --from 2026-06-10 --to 2026-06-08`
- **THEN** system returns error indicating start date is after end date

---

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

### Requirement: Simulated time context
The system SHALL provide a time-aware context to strategies during backtest where `datetime.now()` returns the current bar's timestamp, not wall-clock time.

#### Scenario: Strategy sees replayed timestamp
- **WHEN** strategy code calls `datetime.now()` during backtest
- **THEN** the timestamp returned matches the current bar's timestamp

#### Scenario: Time advances with bars
- **WHEN** successive bars are processed during backtest
- **THEN** `datetime.now()` returns monotonically increasing timestamps

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

### Requirement: Order execution simulation
The system SHALL accept orders from the strategy during backtest and execute them at bar close (OHLC) with no slippage, immediately confirming fills.

#### Scenario: Market order fills at bar close
- **WHEN** strategy places a market order during on_bar() hook
- **THEN** system fills the order at the bar's close price at end of bar processing

#### Scenario: Position limit enforcement
- **WHEN** strategy tries to exceed configured position limits
- **THEN** system rejects the order and logs rejection reason

#### Scenario: Order is rejected
- **WHEN** strategy places an order that violates constraints
- **THEN** order is not executed and a rejection event is sent to strategy

---

### Requirement: Trade record generation
The system SHALL record all executed trades to the `backtest_trades` table with timestamp, symbol, quantity, entry/exit price, P&L, and related strategy metadata.

#### Scenario: Filled order is recorded as trade
- **WHEN** an order is executed during backtest
- **THEN** a record is inserted into `backtest_trades` with execution details

#### Scenario: Trade includes profitability metrics
- **WHEN** a trade is closed (position exits)
- **THEN** `backtest_trades` includes entry_price, exit_price, quantity, and realized_pnl

---

### Requirement: Daily equity snapshot
The system SHALL compute daily equity curves and store them in the `backtest_daily` table with date, cumulative P&L, peak equity, and drawdown metrics.

#### Scenario: Daily snapshot at market close
- **WHEN** last bar of trading day is processed
- **THEN** system records daily summary (date, starting_equity, ending_equity, trades_that_day)

#### Scenario: Drawdown calculation
- **WHEN** daily equity curve is computed
- **THEN** `backtest_daily` includes max_drawdown and current_drawdown_pct

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

### Requirement: CSV export
The system SHALL export backtest results to CSV files in the `backtest/results/` directory, one file per backtest_run with trades and daily curves.

#### Scenario: Results exported to CSV
- **WHEN** backtest completes
- **THEN** files are written to `backtest/results/<run_id>/trades.csv` and `backtest/results/<run_id>/daily.csv`

#### Scenario: CSV files are readable
- **WHEN** CSV files are created
- **THEN** they follow standard CSV format with headers and can be opened in spreadsheet software

---

### Requirement: Leg-grouped trade summary
The backtest SHALL, in addition to any per-order detail, produce a leg-grouped summary in which
each open-through-cover leg is a single row. Scale-in orders SHALL be folded into their parent
leg via a running average entry price and a cumulative lot count. Each leg row SHALL report the
entry time (IST), the exit time (IST), the average entry price, the exit price, the lot count,
the realized leg profit and loss, and the close reason (one of flip, leg_stop, day_stop, or
square-off).

#### Scenario: Scale-ins fold into one leg
- **WHEN** a leg is opened and scaled in over several bars, then covered
- **THEN** the summary shows a single row whose average entry reflects all entry fills and whose
  lot count equals the total lots covered

#### Scenario: Close reason is reported
- **WHEN** a leg is closed by a flip, a per-leg stop, the daily loss cap, or end-of-day square-off
- **THEN** the leg row's reason column states which of those caused the close

#### Scenario: Leg P&L reconciles to the day total
- **WHEN** all leg rows for a day are summed
- **THEN** the total realized leg P&L equals the day's realized P&L reported by the per-order view

---

### Requirement: Backtest query interface
The system SHALL expose a REST endpoint to query backtest results by strategy_id, date range, and filtering by backtest_run metadata.

#### Scenario: Query backtests for a strategy
- **WHEN** user calls `GET /api/backtests?strategy_id=<id>`
- **THEN** system returns list of backtest_runs for that strategy

#### Scenario: Filter by date range
- **WHEN** user calls `GET /api/backtests?from=<date>&to=<date>`
- **THEN** system returns backtest_runs within the specified range

#### Scenario: Fetch trade details
- **WHEN** user calls `GET /api/backtests/<run_id>/trades`
- **THEN** system returns list of trades from `backtest_trades` for that run

### Requirement: Backtest output reports gross and net P&L
The system SHALL report both gross P&L (premium collected minus premium paid, no costs) and net P&L (gross minus all commissions) in backtest output. Both values SHALL be present in the per-day result dict and the final summary table. The per-day `Trade` record SHALL carry a `commission_inr` field populated by `CommissionCalculator` at fill time.

#### Scenario: Per-day output shows gross, commission, and net columns
- **WHEN** `backtest_multiday.py` completes simulation for a trading day
- **THEN** the printed day summary line shows `Net premium: <gross>  Charges: -<commission_total>  Realized: <net>` where `net = gross - commission_total`

#### Scenario: Final summary includes net P&L totals
- **WHEN** the multi-day backtest summary is printed
- **THEN** each day row in the summary table includes a `Net` column (= gross - commission), and the footer shows `Total gross`, `Total commission`, `Total net`, and `Avg daily net`

#### Scenario: Commission is calculated per fill not per day
- **WHEN** a `Trade` is recorded (BUY or SELL)
- **THEN** `trade.commission_inr` is set to the result of `CommissionCalculator.calculate(side=trade.side, turnover_inr=trade.qty * trade.price)` at the time of fill

#### Scenario: --no-commission flag suppresses cost deduction
- **WHEN** `backtest_multiday.py --no-commission` is run
- **THEN** all `commission_inr` values are 0.00, gross P&L equals net P&L, and the output notes `[commissions disabled]`

### Requirement: Batch option-chain pre-loading

The backtest SHALL pre-load option bars in batch rather than querying per signal bar. For each
distinct expiry in the backtest range the system SHALL issue at most one `option_bars` query,
filtered by `underlying`, `expiry_date`, `option_type`, `timeframe`, and a `ts` range covering all
that expiry's trade-days, using the `(underlying, expiry_date, option_type, ts)` index. Loaded bars
SHALL be grouped in memory by `(trade_date, option_type, strike)` and resampled once to the signal
timeframe. The total number of option-bar queries for a run SHALL be O(number of expiries), not
O(number of signal bars).

#### Scenario: One query per expiry

- **WHEN** a backtest spans N trading days across M distinct weekly expiries
- **THEN** the system issues at most M option-bar queries (plus one NIFTY spot query for the range)
- **AND** the per-bar inner loop performs no MongoDB reads

#### Scenario: Results are unchanged

- **WHEN** the same backtest window is run with batch pre-loading
- **THEN** the replayed trades, per-leg P&L, and summary totals are identical to the per-bar reader

### Requirement: In-memory nearest-strike fallback

When the exact target strike is absent for a `(trade_date, option_type)`, the backtest SHALL select
the nearest available strike within `WAREHOUSE_STRIKE_BAND` grid steps from the already pre-loaded
chain, without issuing additional MongoDB queries. The live broker API MAY be consulted only when
no strike in the band was pre-loaded.

#### Scenario: Substitute strike served from memory

- **WHEN** the exact strike has no bars but a strike within the band does
- **THEN** the nearest in-band strike is used and the substitution is logged
- **AND** no extra MongoDB query is issued to find it

### Requirement: Backtest performance instrumentation

The backtest SHALL record and log, via `structlog`, the total elapsed wall-clock time, per-day
elapsed time, and the count of option-bar queries issued. These metrics SHALL be emitted at the end
of a run so the O(expiries) query budget and the sub-minute target can be verified.

#### Scenario: Timing emitted

- **WHEN** a multi-day backtest completes
- **THEN** a structured log line reports `elapsed_s`, `days`, and `option_queries`

