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

