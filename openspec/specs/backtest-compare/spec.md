# backtest-compare Specification

## Purpose
TBD - created by archiving change backtest-today-compare. Update Purpose after archive.
## Requirements
### Requirement: Paper-vs-backtest comparison script
The system SHALL provide `scripts/backtest_compare.py`, a standalone script that replays the
SuperTrend option-selling strategy on historical MongoDB bars for a given date and prints a
side-by-side comparison of simulated P&L against that day's paper journal stats. The script
SHALL NOT write to any PostgreSQL table.

#### Scenario: Run comparison for today
- **WHEN** user runs `python scripts/backtest_compare.py --date 2026-06-12`
- **THEN** script prints a table with backtest trades, simulated net P&L, paper journal P&L,
  and a delta column showing the difference

#### Scenario: No bars available
- **WHEN** the target date has no NIFTY 5m bars in MongoDB
- **THEN** script prints "No market bars found for <date>" and exits with code 1

#### Scenario: No paper journal for the date
- **WHEN** the target date has bars but no paper_journal document in MongoDB
- **THEN** script prints the backtest result alone and notes "No paper journal for <date>"

#### Scenario: SuperTrend warmup with prior-day bars
- **WHEN** prior-day NIFTY 5m bars exist in MongoDB
- **THEN** script seeds the SuperTrendTracker with the last `period` bars of the prior session
  before replaying today's bars, so the direction is correctly initialized at market open

### Requirement: Comparison output format
The comparison script SHALL print a structured text report with three sections: (1) a
trade-by-trade backtest log showing entry/exit IST times, symbol, lots, entry price, exit price,
P&L, and close reason; (2) a summary table comparing backtest vs paper on trades, wins, losses,
win rate, gross premium sold, gross premium bought, and net realized P&L; (3) a delta row
showing the absolute difference between backtest and paper for each numeric metric.

#### Scenario: Report sections present
- **WHEN** both backtest and paper data are available for the date
- **THEN** output contains all three sections: trade log, summary table, delta row

#### Scenario: Metrics match journal schema
- **WHEN** paper stats are read from MongoDB paper_journal
- **THEN** the comparison uses the same field names as `compute_daily_stats()` output
  (gross_premium_sold, gross_premium_bought, net_premium, realized_pnl, round_trips, win_rate)

### Requirement: Parameter-sweep grid runner
The system SHALL provide `scripts/backtest_sweep.py`, a standalone script that runs the
config-driven backtest engine across a grid of `StrategyConfig` variants over one historical window
and prints a ranked comparison table. The script SHALL load raw 1-minute spot and option-chain data
for the window once and reuse it across all combos (resampling per timeframe in memory). The default
grid SHALL cover SuperTrend settings {(3,1),(10,2),(10,3)} × timeframes {3,5,15,30,60}m × moneyness
{ITM 1/2/3, ATM, OTM 1/2/3}. CLI flags SHALL allow subsetting each axis (`--st`, `--tf`,
`--moneyness`) and the window (`--days`, `--start`). The script SHALL NOT write to any database.

#### Scenario: Run the default grid
- **WHEN** user runs `python scripts/backtest_sweep.py --days 90 --start 2026-06-12`
- **THEN** the script runs each grid combo over the window and prints one comparison row per combo

#### Scenario: Data loaded once
- **WHEN** the sweep runs N combos over the same window
- **THEN** the spot and option chains are queried from MongoDB once, not per combo

#### Scenario: Subset an axis
- **WHEN** user runs the sweep with `--st 10,2 --tf 15`
- **THEN** only combos with SuperTrend (10,2) and the 15m timeframe are evaluated

### Requirement: Ranked comparison output
The sweep SHALL aggregate, per combo, at least: total net P&L, gross profit, gross loss, profit
factor, win rate, max drawdown, total trades, and days stopped. It SHALL print a table sorted by
profit factor descending then net P&L descending, and SHALL NOT auto-select a winner — the user
chooses from the table.

#### Scenario: Metrics present per combo
- **WHEN** the comparison table is printed
- **THEN** each row shows the combo's SuperTrend/timeframe/moneyness and its net, profit factor,
  win rate, max drawdown, and trade count

#### Scenario: Sorted by profit factor
- **WHEN** the table is printed
- **THEN** rows are ordered by profit factor descending, ties broken by net P&L descending

### Requirement: Single-config run path
The system SHALL support running exactly one chosen `StrategyConfig` (via `--config <json>` or
single-combo flags) that prints the full per-day and per-leg detail for that config, so a promoted
config can be inspected in depth. The same JSON SHALL be a valid `StrategyConfig.from_dict` payload.

#### Scenario: Run one config in detail
- **WHEN** user runs the sweep script with a single `--config <json>`
- **THEN** the script runs only that config and prints the per-day/per-leg breakdown

#### Scenario: Config JSON is reusable
- **WHEN** a config JSON used by the single-config path is loaded via `StrategyConfig.from_dict`
- **THEN** it produces an equivalent config object (the frontend can reuse the same payload)

