## ADDED Requirements

### Requirement: Instruments-table expiry resolution is the source of truth

The system SHALL resolve the next tradeable expiry per underlying from the instruments table
(the Dhan scrip master), not from a forward-projected weekday calendar. Resolution SHALL
return the smallest option `expiry` on or after a floor date for that underlying across
`CE`/`PE` contracts, and SHALL be cadence-agnostic (correct for weekly, monthly-only, and
weekday-shifted regimes without any hardcoded weekday arithmetic).

#### Scenario: Monthly-only underlying resolves to its monthly expiry

- **WHEN** the next expiry is resolved for an underlying whose exchange lists only monthly
  expiries (e.g. BANKNIFTY)
- **THEN** the resolved expiry is that underlying's next monthly expiry from the instruments
  table
- **AND** no synthetic weekly expiry is ever returned

#### Scenario: Weekday-shifted weekly resolves correctly

- **WHEN** the next expiry is resolved for an underlying whose weekly expiry weekday differs
  from another index (e.g. SENSEX Tuesday vs NIFTY's weekday)
- **THEN** the resolved expiry matches the actual instrument expiry weekday, sourced from the
  instruments table rather than fixed weekday math

#### Scenario: No fabricated expiry when the table has none

- **WHEN** the instruments table has no matching expiry for the underlying on or after the
  floor date
- **THEN** resolution returns no expiry (null / `available: false`) rather than a projected
  date
