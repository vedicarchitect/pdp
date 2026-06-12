# paper-monitor-cli Specification

## Purpose
TBD - created by archiving change add-paper-monitor-cli. Update Purpose after archive.
## Requirements
### Requirement: Read-only polling monitor
The system SHALL provide a terminal monitor (`monitor.pl`) that polls Redis and the platform's
read-only REST endpoints approximately once per second and renders the live paper session. The
monitor SHALL perform no order mutation or any other side effect; all trading logic stays in the
platform.

#### Scenario: Monitor renders without mutating state
- **WHEN** the monitor runs against a live paper session
- **THEN** it displays current NIFTY price, SuperTrend direction, and per-strategy blotters, and
  it issues no order-placing or state-changing calls

#### Scenario: Redis drop is tolerated
- **WHEN** the Redis connection drops
- **THEN** the monitor attempts to reconnect and continues rendering once reconnected

### Requirement: Dynamic weekly expiry resolution
The monitor SHALL resolve the nearest NIFTY weekly expiry **dynamically** at runtime (the next
Tuesday, NIFTY's weekly expiry day) rather than from a hard-coded date, refresh it when the
calendar day rolls over, and label displayed instruments from the resolved expiry.

#### Scenario: Expiry follows the calendar
- **WHEN** the current weekly expiry has passed
- **THEN** the monitor requests the next weekly expiry's option chain and labels legs with that
  expiry, without code edits

#### Scenario: Instrument labels match the resolved expiry
- **WHEN** a leg is displayed
- **THEN** its instrument label uses the dynamically resolved expiry, not a hard-coded month/day

### Requirement: Risk-stop visibility
The monitor SHALL display the strategy's configured per-leg stop and daily loss cap and indicate
when an open leg's mark-to-market is approaching its per-leg stop, so that a stop-driven close is
explainable on screen.

#### Scenario: Approaching leg stop is flagged
- **WHEN** an open leg's unrealized loss is within the alert band of `leg_stop_per_lot × lots`
- **THEN** the monitor highlights that leg to indicate it is near its stop

#### Scenario: Day cap progress is shown
- **WHEN** the session has realized P&L for the day
- **THEN** the monitor shows realized P&L against the configured daily loss cap

