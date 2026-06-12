# market-data

## ADDED Requirements

### Requirement: Universal SuperTrend indicator
The market engine SHALL compute a SuperTrend indicator once per `(security_id, timeframe)` on
each closed bar and make its latest value and direction available to strategies, which consume
it without recomputing.

#### Scenario: Direction available after seeding
- **WHEN** at least `period` bars have closed for a `(security_id, timeframe)`
- **THEN** the latest SuperTrend exposes a direction of up (+1) or down (-1) and a line value

#### Scenario: Direction undefined before seeding
- **WHEN** fewer than `period` bars have closed
- **THEN** the SuperTrend value is unavailable (no direction emitted)

#### Scenario: Computed before strategy dispatch
- **WHEN** a bar closes
- **THEN** the SuperTrend is updated before the bar is dispatched to strategies, so strategies
  read the value for that bar
