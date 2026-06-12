# instrument-registry

## ADDED Requirements

### Requirement: Daily filtered instrument snapshot
The system SHALL persist, once per trading day, a date-stamped snapshot of the scrip-master rows
whose underlying is one of a configured allowed set — defaulting to `NIFTY`, `BANKNIFTY`, and
`SENSEX` — together with those three index instruments themselves. The allowed set SHALL be
configurable so its scope can be widened without changing the snapshot mechanism. Writing a given
day's snapshot SHALL be idempotent (re-running the same day replaces that day's snapshot).

#### Scenario: Snapshot keeps only allowed underlyings
- **WHEN** the daily snapshot runs against the full scrip master
- **THEN** the stored snapshot contains only rows whose underlying is in the allowed set (plus
  the allowed index instruments), and excludes all other underlyings

#### Scenario: Snapshot is idempotent per day
- **WHEN** the snapshot for a given date is produced twice
- **THEN** the second run replaces the first and the stored row count is unchanged

### Requirement: Historical instrument lookup by date
The system SHALL resolve instrument details (including expiry, strike, and `security_id`) for a
historical date by reading the snapshot taken on or before that date (the latest snapshot whose
date is ≤ the requested date), so a backtest resolves the contracts that were active then rather
than only those currently active.

#### Scenario: Latest snapshot on or before the date is used
- **WHEN** a lookup is requested for a date that has a snapshot on or before it
- **THEN** the system returns instruments from the most recent snapshot with date ≤ the requested
  date

#### Scenario: Expired contract resolves from a historical snapshot
- **WHEN** a backtest requests a NIFTY weekly contract that has since expired, for a past date
  covered by a snapshot
- **THEN** the contract's `security_id`, expiry, and strike are resolved from that snapshot even
  though the contract no longer appears in the live `instruments` table

#### Scenario: No snapshot available
- **WHEN** no snapshot exists on or before the requested date
- **THEN** the lookup reports the absence so the caller can fall back to the expired-options
  warehouse
