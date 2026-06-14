## MODIFIED Requirements

### Requirement: Paper-vs-backtest comparison script
The system SHALL provide `backtest/compare.py` (moved from `scripts/backtest_compare.py`) as a
standalone script that replays the SuperTrend option-selling strategy on historical MongoDB bars
for a given date and prints a side-by-side comparison of simulated P&L against that day's paper
journal stats. The script SHALL NOT write to any PostgreSQL table. The `task backtest:compare`
Taskfile task SHALL invoke `backtest/compare.py` instead of `scripts/backtest_compare.py`.

#### Scenario: Run comparison for a date
- **WHEN** user runs `task backtest:compare -- --date 2026-06-12`
- **THEN** script prints a table with backtest trades, simulated net P&L, paper journal P&L,
  and a delta column showing the difference

#### Scenario: No bars available
- **WHEN** the target date has no NIFTY bars in MongoDB
- **THEN** script prints "No market bars found for <date>" and exits with code 1

#### Scenario: No paper journal for the date
- **WHEN** the target date has bars but no paper_journal document in MongoDB
- **THEN** script prints the backtest result alone and notes "No paper journal for <date>"

#### Scenario: SuperTrend warmup with prior-day bars
- **WHEN** prior-day NIFTY bars exist in MongoDB
- **THEN** script seeds the SuperTrendTracker with the last `period` bars of the prior session
  before replaying today's bars, so the direction is correctly initialized at market open

## REMOVED Requirements

### Requirement: Parameter-sweep grid runner (scripts/backtest_sweep.py)
**Reason**: `scripts/backtest_sweep.py` is superseded by `backtest/run.py` which consolidates
sweep + single-config detail into one canonical script.
**Migration**: Use `task backtest:sweep -- [flags]` (now runs `backtest/run.py`) or
`uv run python backtest/run.py [flags]` directly. All flags are identical.
