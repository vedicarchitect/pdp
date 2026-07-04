## ADDED Requirements

### Requirement: Strategy-agnostic decision-event persistence
The system SHALL persist a backtest's decision events to a `backtest_decisions` collection using a
strategy-agnostic schema, so the reasoning of any strategy (not only the directional strangle) is
captured uniformly. Each decision event SHALL record the run id, the IST timestamp, a typed
event/reason code, the action taken, and the indicator/bias snapshot at that moment (e.g. bias
score/bucket/votes, SuperTrend state, EMAs, VIX, PCR, open legs, P&L). The reason codes SHALL cover
at least: `st_flip`, `entry`, `scale_in`, `rollup` (with a premium-decay trigger), `exit` (with a
`tp`/`stop`/`flip`/`squareoff` sub-reason), and `reentry` (with a cool-off trigger).

#### Scenario: A day's decision events are persisted with reasons
- **WHEN** a backtest day produces entries, scale-ins, rollups, and exits
- **THEN** a `backtest_decisions` event exists for each with its reason code, action, and the indicator/bias snapshot at that timestamp

#### Scenario: Why-entry and why-exit are answerable from the DB
- **WHEN** the decision trace for a run and date is queried
- **THEN** the sequence of reason-coded events (e.g. ST flip → scale-in → entry → rollup on premium decay → cool-off reentry → exit) is returned without reading any local file

### Requirement: Events-by-default, full trace on demand
The system SHALL, by default, store only the discrete decision events plus a per-day summary for a
run — it SHALL NOT store a snapshot for every minute of every run or every sweep combination. The
full per-minute trace (every bar, including minutes with no action) SHALL be materialized on demand
for a specific run and date when explicitly requested, rather than persisted eagerly.

#### Scenario: Default storage is events-only
- **WHEN** a backtest (including a sweep combination) completes without a full-trace request
- **THEN** only its decision events and per-day summary are persisted, not a per-minute snapshot for every bar

#### Scenario: Full per-minute trace is produced on request
- **WHEN** a full per-minute trace is requested for a specific run and date
- **THEN** the every-minute snapshot for that day is materialized and returned, including quiet minutes with no decision event

### Requirement: Decision events routed to OpenSearch
The system SHALL route decision events to a `backtest-decisions` OpenSearch family (following the
existing indexer/mapping/sink convention) so decisions are scannable at minute granularity in the
observability layer and can be aligned against live/paper decisions for the same timestamp.

#### Scenario: Decision events are queryable in OpenSearch
- **WHEN** a run's decision events are indexed
- **THEN** they appear in the `backtest-decisions` index keyed by run and timestamp and are filterable by reason code

### Requirement: Decision-trace read API
The system SHALL expose an endpoint under `/api/v1/strangle-backtests` that returns the decision
trace for a given run and date — the ordered decision events with their reason codes and snapshots
by default, and the full per-minute trace when the full-trace option is requested.

#### Scenario: The decision trace endpoint returns events
- **WHEN** the decision-trace endpoint is requested for a run and date
- **THEN** the ordered decision events with reason codes and indicator snapshots are returned

#### Scenario: The decision trace endpoint returns the full trace on request
- **WHEN** the decision-trace endpoint is requested with the full-trace option for a run and date
- **THEN** the every-minute snapshot for that day is returned
