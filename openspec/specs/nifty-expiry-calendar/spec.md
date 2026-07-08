# Spec: nifty-expiry-calendar

## Purpose

Provides authoritative NIFTY expiry-date resolution for backtesting and live trading. Resolves
`(trade_date, expiry_flag, expiry_code) → real expiry_date` using a pre-built JSON cache. Encodes
historical weekday regime changes and exchange-holiday shifts sourced from real expiry data rather
than fixed weekday arithmetic.

---
## Requirements
### Requirement: Real NIFTY expiry-date resolution

The system SHALL provide a NIFTY expiry calendar that resolves
`(trade_date, expiry_flag, expiry_code) → real expiry_date`, where `expiry_code=N` selects the
`N`-th `expiry_flag` (`WEEK`|`MONTH`) expiry on or after `trade_date`. The calendar MUST encode the
historical expiry-weekday regimes (NIFTY weekly expiry has changed weekday over time) and holiday
shifts, sourced from real expiry data rather than fixed weekday arithmetic.

#### Scenario: Resolve nearest weekly expiry

- **WHEN** `resolve_expiry(trade_date, "WEEK", 1)` is called
- **THEN** it returns the first NIFTY weekly expiry date on or after `trade_date`
- **AND** `expiry_code=2` returns the second such expiry

#### Scenario: Expiry day counts as code 1

- **WHEN** `trade_date` is itself an expiry day
- **THEN** `resolve_expiry(trade_date, flag, 1)` returns that same date

#### Scenario: Weekday regime change is honoured

- **WHEN** a `trade_date` falls in a period where NIFTY weekly expiry was on a different weekday
  than the current convention
- **THEN** the resolved `expiry_date` matches the actual expiry weekday for that period

#### Scenario: Holiday-shifted expiry

- **WHEN** a scheduled expiry falls on an exchange holiday
- **THEN** the resolved `expiry_date` is the actual shifted trading day, not the holiday

---

### Requirement: Expiry calendar cache

The system SHALL read the expiry calendar from a pre-built JSON cache (`{flag: ["YYYY-MM-DD", ...]}`
format). Runtime resolution MUST NOT require any external database connection. The cache is built
once and updated as new expiries are observed.

#### Scenario: Cache loads and resolves

- **WHEN** `NiftyExpiryCalendar.load(cache_path)` is called
- **THEN** weekly and monthly expiry dates are available for resolution
- **AND** `resolve_expiry` operates entirely from in-memory data with no I/O

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

