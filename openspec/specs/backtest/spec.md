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
The system SHALL replay historical market bars from MongoDB `market_bars` collection in chronological order, feeding them to the strategy via the same event-driven interface as live trading.

#### Scenario: Bars arrive in correct order
- **WHEN** backtest processes historical bars for a security between two dates
- **THEN** bars are processed in ascending timestamp order, one at a time

#### Scenario: On-bar hook is invoked
- **WHEN** a historical bar arrives during backtest replay
- **THEN** the strategy's `on_bar()` hook is called with the bar data

#### Scenario: Missing bars in history
- **WHEN** backtest encounters a gap in market_bars history
- **THEN** system logs a warning with the gap period and continues processing

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
The system SHALL pre-compute all required indicators once per (security, timeframe) over the backtest date range using vectorized Polars operations, making them available to the strategy during replay.

#### Scenario: Indicator cache is pre-populated
- **WHEN** backtest is initialized
- **THEN** all indicators required by the strategy are computed for the date range

#### Scenario: Strategy accesses indicator during replay
- **WHEN** strategy requests an indicator value during on_bar() hook
- **THEN** system returns the pre-computed value for the current bar's timestamp

#### Scenario: Indicator computation spans full history
- **WHEN** backtest begins
- **THEN** indicator pre-compute covers entire date range, not just live bars

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
The system SHALL create a `backtest_runs` table row for each backtest with strategy_id, date range, start/end equity, total trades, and configuration snapshot.

#### Scenario: Backtest run is recorded
- **WHEN** backtest completes
- **THEN** a record is inserted into `backtest_runs` with strategy_id, from_date, to_date, start_equity, end_equity

#### Scenario: Configuration snapshot is stored
- **WHEN** backtest run is recorded
- **THEN** `backtest_runs` includes a JSON column with strategy config at backtest time

---

### Requirement: CSV export
The system SHALL export backtest results to CSV files in the `backtest/results/` directory, one file per backtest_run with trades and daily curves.

#### Scenario: Results exported to CSV
- **WHEN** backtest completes
- **THEN** files are written to `backtest/results/<run_id>/trades.csv` and `backtest/results/<run_id>/daily.csv`

#### Scenario: CSV files are readable
- **WHEN** CSV files are created
- **THEN** they follow standard CSV format with headers and can be opened in spreadsheet software

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

