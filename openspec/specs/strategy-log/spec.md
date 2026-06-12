# strategy-log

## Requirements

### Requirement: Per-strategy daily log file
Every strategy SHALL write its own run log to a single file per strategy per trading day, named by
strategy id and IST date (e.g. `logs/<strategy_id>/<YYYY-MM-DD>.log`), in append mode, using
`structlog` (no bare `print`/`rich`). A new file SHALL begin when the IST date changes; a mid-day
process restart SHALL continue appending to the same day's file. The mechanism SHALL be provided
generically so any strategy is logged without per-strategy logging code, and SHALL apply
unchanged whether the run is paper or live.

#### Scenario: Each strategy writes its own day file
- **WHEN** a strategy runs during a trading day
- **THEN** its header, heartbeat, and decision lines are appended to that strategy's date-stamped
  file as one continuous timeline

#### Scenario: New day, new file
- **WHEN** the IST calendar date changes
- **THEN** subsequent lines are written to a new file named for the new date

#### Scenario: Restart appends
- **WHEN** the process restarts during the same trading day
- **THEN** new lines append to the existing day file rather than overwriting it

#### Scenario: Generic across strategies
- **WHEN** a strategy provides no logging-specific code of its own
- **THEN** it still produces a config header, heartbeats, and decision lines via the shared mechanism

### Requirement: Run-start configuration header
At the start of each strategy run, the strategy SHALL log the effective configuration it resolved
for that run — the merged parameters plus any settings that affected the run — together with the
strategy id, the run mode (paper or live), the signal timeframe, and the watchlist, so the run is
reproducible from the log header alone. The header SHALL be emitted once at run start.

#### Scenario: Config header at run start
- **WHEN** a strategy run begins
- **THEN** the first lines of that run's day file record the resolved parameters, strategy id, run
  mode, timeframe, and watchlist

#### Scenario: Mode is recorded
- **WHEN** the run starts in paper mode (or, later, live mode)
- **THEN** the header records which mode the run used

### Requirement: Per-minute state heartbeat
While running within its trading window, each strategy SHALL emit, approximately once per minute,
a structured heartbeat snapshotting its current state and open positions. Common fields SHALL be
strategy-agnostic (identity, mode, open positions, day P&L); a strategy MAY contribute additional
snapshot fields. The heartbeat SHALL NOT be emitted outside the trading window.

#### Scenario: Heartbeat each minute in the window
- **WHEN** the strategy is within its trading window
- **THEN** about once per minute it writes a heartbeat line with the common state fields

#### Scenario: Strategy-specific fields included
- **WHEN** a strategy contributes extra heartbeat fields (e.g. SuperTrend direction, open leg, MTM,
  stop distances)
- **THEN** those fields appear in that strategy's heartbeat lines

#### Scenario: No heartbeat outside the window
- **WHEN** the current time is before the start or after the square-off
- **THEN** no heartbeat line is written

### Requirement: Decision log
Each strategy SHALL log a line at the moment of each trading decision — such as open, scale-in,
flip, stop-out, or square-off — stating the action and its reason, on the same timeline and in the
same file as the heartbeat.

#### Scenario: Action produces a decision line
- **WHEN** the strategy takes a trading action
- **THEN** a decision line is written naming the action and its reason
