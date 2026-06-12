# supertrend-strategy

## MODIFIED Requirements

### Requirement: Trading window and square-off
The strategy SHALL place no new entries before the configured start time (IST) and SHALL flat
all legs at the configured square-off time (IST), trading no more that day. The start and
square-off times SHALL be compared against the **closed bar's timestamp** (converted to IST),
not against wall-clock time, so live and backtest scheduling are identical and the strategy can
be driven deterministically from historical bars.

#### Scenario: No entries before start
- **WHEN** the current bar's IST timestamp is before the start time
- **THEN** the strategy places no orders

#### Scenario: Square-off at end of window
- **WHEN** the current bar's IST timestamp is at or past the square-off time and a leg is open
- **THEN** the strategy buys back the open leg and stops trading for the day
