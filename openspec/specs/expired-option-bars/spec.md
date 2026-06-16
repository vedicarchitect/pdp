# expired-option-bars Specification

## Purpose
TBD - created by archiving change store-expired-options-mongo. Update Purpose after archive.
## Requirements
### Requirement: Expired-option bar storage

The system SHALL persist OHLCV bars of expired option contracts in a dedicated MongoDB
time-series collection `expired_option_bars`, keyed by an ATM-relative rolling-series
identity rather than by `security_id` (which no longer exists for expired contracts).

Each document MUST use `ts` as the time field (UTC) and a `metadata` sub-document as the
meta field containing `underlying`, `expiry_flag` (`WEEK`|`MONTH`), `expiry_code`,
`strike_label` (`ATM`|`ATM±N`), `option_type` (`CE`|`PE`), and `timeframe`. Bar fields are
`open`, `high`, `low`, `close`, `volume`, `oi`, `iv`.

#### Scenario: Collection initialised at startup

- **WHEN** `init_collections` runs
- **THEN** a MongoDB time-series collection `expired_option_bars` exists with
  `timeField=ts`, `metaField=metadata`, granularity `seconds`
- **AND** initialisation is idempotent when the collection already exists

#### Scenario: Bar document shape

- **WHEN** an expired-option bar is written
- **THEN** it contains `ts` (UTC datetime) and `metadata.{underlying, expiry_flag,
  expiry_code, strike_label, option_type, timeframe}`
- **AND** it contains numeric `open`, `high`, `low`, `close`, `volume`, `oi`, `iv`

### Requirement: Expired-option bar backfill

The system SHALL provide a backfill command that warehouses expired-option bars from
Dhan's `expired_options_data` API. It MUST request data in chunks of at most 30 days per
call, respect the data-API rate limit, and use `expiry_code=1` (the nearest expiry from
the `from_date`). The command MUST be idempotent: re-running over an already-populated
range SHALL insert zero duplicate bars.

#### Scenario: Backfill populates the warehouse

- **WHEN** the backfill runs for a date range and a set of `(expiry_flag, expiry_code,
  strike_label, option_type)` combinations
- **THEN** the API is queried in ≤30-day chunks with `expiry_code=1`
- **AND** parsed bars are inserted into `expired_option_bars` with UTC timestamps

#### Scenario: Re-running the backfill is idempotent

- **WHEN** the backfill is run a second time over the same range
- **THEN** no duplicate bars are inserted (existing timestamps are detected and skipped)

#### Scenario: Nested API payload is unwrapped before side selection

- **WHEN** the API response wraps bars as `data["data"]["ce"|"pe"]`
- **THEN** the nested `data` wrapper is unwrapped before the `ce`/`pe` side is selected
- **AND** the resulting OHLCV arrays are parsed into bar documents

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

