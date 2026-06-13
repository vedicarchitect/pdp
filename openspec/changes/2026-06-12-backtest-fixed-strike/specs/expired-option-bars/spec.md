## MODIFIED Requirements

### Requirement: Backtest reads expired bars from MongoDB

The backtest SHALL read expired-option bars from the unified `option_bars` warehouse, keyed by the
real contract `(underlying, expiry_date, strike, option_type, timeframe)`, rather than from the
ATM-relative `expired_option_bars` collection. The `expired_option_bars` collection is
**deprecated and read-only**: it is retained for historical reference but is no longer the backtest
source and receives no new writes. On a cache miss the backtest MAY fall back to the live Dhan API
and MUST upsert the fetched bars into `option_bars`.

#### Scenario: Expired day priced from the unified warehouse

- **WHEN** the backtest simulates a day whose expiry is absent from the instruments table and
  matching bars exist in `option_bars`
- **THEN** option legs are priced from `option_bars` by fixed strike + expiry without calling the
  live API

#### Scenario: Cache miss falls back to API and persists to option_bars

- **WHEN** the backtest needs bars not present in `option_bars`
- **THEN** it fetches them from the live Dhan API
- **AND** upserts the fetched bars into `option_bars` (not `expired_option_bars`) for subsequent runs

#### Scenario: Deprecated collection receives no new writes

- **WHEN** any producer writes option bars
- **THEN** the write targets `option_bars`
- **AND** `expired_option_bars` is left unchanged
