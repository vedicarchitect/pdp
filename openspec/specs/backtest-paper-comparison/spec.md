# backtest-paper-comparison Specification

## Purpose
TBD - created by archiving change backtest-paper-comparison. Update Purpose after archive.
## Requirements
### Requirement: Per-strategy paper realized P&L
The system SHALL compute realized P&L per `strategy_id` over an arbitrary date window from
PostgreSQL by joining `trades` to `orders` on `order_id`, filtering `orders.mode = 'PAPER'`, and
grouping by `orders.strategy_id`, using the same realized-P&L semantics as
`pdp/journal/stats.py:compute_daily_stats`. An index SHALL exist on `orders.strategy_id` to support
the query. The computation SHALL be generic — it SHALL NOT be specific to any one strategy.

#### Scenario: Realized P&L is grouped by strategy over a window
- **WHEN** the per-strategy P&L is requested for a date window
- **THEN** paper realized P&L is returned per `strategy_id`, derived from paper trades joined to their orders

#### Scenario: Only paper trades are included
- **WHEN** both paper and live trades exist for a strategy
- **THEN** only trades whose order `mode` is `PAPER` contribute to the paper P&L

### Requirement: Backtest-vs-paper alignment API
The system SHALL expose `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` that aligns a backtest
run's per-day equity/P&L series against the live paper realized P&L for the same `strategy_id` over
the run's window, returning both series and the per-day divergence, suitable for overlay and
inspection.

#### Scenario: A run is aligned against paper
- **WHEN** the vs-paper endpoint is requested for a run whose strategy has paper trades in the window
- **THEN** the backtest per-day series and the paper per-day series are returned aligned by date, with a per-day divergence column

#### Scenario: No paper data in the window
- **WHEN** the vs-paper endpoint is requested for a run whose strategy has no paper trades in the window
- **THEN** the backtest series is returned with the paper series empty and a clear "no paper data" indication rather than an error

### Requirement: Minute-level decision diff
The system SHALL align a backtest run's decision events (from the `backtest-decision-trace`
capability) with the live/paper decision events for the same `strategy_id` and timestamp, using a
shared event vocabulary, so a user can see, for a given date and minute, what the backtest decided
versus what live did.

#### Scenario: A minute's decisions are diffed
- **WHEN** a minute-level diff is requested for a run and date that also has live decisions
- **THEN** for each timestamp the backtest decision/action and the live decision/action are returned side by side, flagging minutes where they differ

### Requirement: Divergence root-causing
The system SHALL annotate per-day or per-minute divergence with likely causes by cross-referencing
the data-coverage gap radar (missing input families such as weekly Camarilla, PCR, or VIX for that
date) and the bias-evaluation votes, so a divergence can be attributed to a concrete cause rather
than left unexplained.

#### Scenario: Divergence attributed to a missing input
- **WHEN** a day diverges and the gap radar reports weekly Camarilla missing for that date on the live side
- **THEN** the divergence for that day is annotated with the missing-input cause

### Requirement: Daily backtest-vs-paper convergence check

The system SHALL provide a daily convergence check, per index, that tracks the cumulative
backtest−paper divergence to date against the backtest-proven trajectory, built on the existing
`/runs/{id}/vs-paper` per-day alignment. For each index it SHALL report cumulative backtest net,
cumulative paper net, their divergence, and the top attributed causes, computed from the
existing per-day alignment rows with no new persistence store. Cause attribution SHALL NOT emit
"futures missing" (that family is removed); a day with no explaining cause SHALL report a null
cause rather than a spurious futures flag.

#### Scenario: Cumulative divergence is tracked per index

- **WHEN** the convergence check is requested for a run that has accumulating paper data
- **THEN** it returns, per index, cumulative backtest net, cumulative paper net, their
  divergence, and the top attributed causes

#### Scenario: No futures cause after removal

- **WHEN** a day that previously attributed its divergence only to "futures missing" is
  re-evaluated
- **THEN** the convergence cause for that day is null (genuinely unexplained) or a real cause,
  never "futures missing"

#### Scenario: No paper data yet is reported plainly

- **WHEN** the convergence check runs for a window in which the strategy has no paper trades
- **THEN** it reports paper data as unavailable for that window and returns the backtest series
  only, without erroring

