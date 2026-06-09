## ADDED Requirements

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

The backtest SHALL read expired-option bars from `expired_option_bars` first whenever it
encounters a trade day whose correct weekly expiry is no longer in the instrument
registry. On a cache miss the backtest MAY fall back to the live `expired_options_data`
API using `expiry_code=1`, and it MUST persist the fetched bars back into the warehouse.

#### Scenario: Expired day priced from the warehouse

- **WHEN** the backtest simulates a day whose expiry is absent from the instruments table
  and matching bars exist in `expired_option_bars`
- **THEN** option legs are priced from the warehoused bars without calling the live API

#### Scenario: Cache miss falls back to API and persists

- **WHEN** the backtest needs expired bars not present in the warehouse
- **THEN** it fetches them from the live API with `expiry_code=1`
- **AND** persists the fetched bars into `expired_option_bars` for subsequent runs
