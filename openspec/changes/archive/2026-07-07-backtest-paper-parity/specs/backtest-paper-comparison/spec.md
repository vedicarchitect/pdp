## ADDED Requirements

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
