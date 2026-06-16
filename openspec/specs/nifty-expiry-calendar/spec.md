# Spec: nifty-expiry-calendar

## Purpose

Provides authoritative NIFTY expiry-date resolution for backtesting and live trading. Resolves
`(trade_date, expiry_flag, expiry_code) → real expiry_date` using a pre-built JSON cache derived
from OI-reset detection over historical DuckDB data. Encodes historical weekday regime changes and
exchange-holiday shifts sourced from real expiry data rather than fixed weekday arithmetic.

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

### Requirement: Expiry calendar build and cache

The system SHALL build the expiry calendar by OI-reset detection over the read-only abi-project
DuckDB and persist it to a JSON cache. Runtime resolution SHALL read the cache and MUST NOT require
a DuckDB connection. The build MUST NOT mutate the source database.

#### Scenario: Build writes a cache consumers can load

- **WHEN** the calendar build runs against the source DuckDB
- **THEN** weekly and monthly expiry dates are detected via OI-reset and written to the JSON cache
- **AND** `NiftyExpiryCalendar.load(cache)` resolves expiries without opening DuckDB
