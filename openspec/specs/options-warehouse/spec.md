# Options Warehouse Spec

## Purpose

Persistent storage for NIFTY option OHLCV bars in MongoDB. A single unified `option_bars`
collection keyed by real contract identity ensures duplicate-free reads for both live-feed and
backfill producers. Stable fixed-strike series support backtesting and analytics without ATM-drift.

## Requirements

### Requirement: Unified option-bars collection keyed by real contract

The system SHALL persist NIFTY option OHLCV bars in a single regular (non-time-series) MongoDB
collection `option_bars`, keyed by the real contract identity
`(underlying, expiry_date, strike, option_type, timeframe, ts)`. Each document MUST contain numeric
`open`, `high`, `low`, `close`, `volume`, `oi`, `iv`; the resolved real `expiry_date` (date),
`strike` (number), `option_type` (`CE`|`PE`), `timeframe` (e.g. `1m`), and UTC `ts`; plus
`underlying`, `expiry_flag` (`WEEK`|`MONTH`), `trading_symbol`, optional `strike_label`, optional
`security_id`, and `source` (`live`|`abi`|`dhan_api`).

#### Scenario: Collection and indexes initialised at startup

- **WHEN** `init_collections` runs
- **THEN** a regular collection `option_bars` exists with a **unique** index on
  `(underlying, expiry_date, strike, option_type, timeframe, ts)`
- **AND** read indexes exist on `(underlying, expiry_date, option_type, ts)` and
  `(underlying, strike, option_type, ts)`
- **AND** initialisation is idempotent when the collection and indexes already exist

#### Scenario: Bar document shape

- **WHEN** an option bar is written
- **THEN** it contains the full contract key plus OHLCV, `oi`, `iv`, `trading_symbol`, and `source`
- **AND** `security_id` is present when the writer knows it (live, or recovered from a snapshot)

### Requirement: Duplicate bars are structurally impossible

The `option_bars` unique index SHALL guarantee that no two documents share the same contract key
and `ts`, regardless of which producer writes. The contract-aware writer MUST upsert idempotently
(first-write-wins) so the live feed and any backfill can target the same warehouse without creating
duplicates.

#### Scenario: Same bar written by two producers

- **WHEN** the same `(contract, ts)` bar is written by both the live feed and a backfill
- **THEN** the warehouse retains exactly one document for that `(contract, ts)`
- **AND** the second write is rejected by the unique index (or no-ops via `$setOnInsert`)

### Requirement: Fixed-contract and trading-symbol storage

Each warehoused bar SHALL represent a **fixed actual-strike contract** (not an ATM-relative rolling
series) and SHALL carry the contract's `trading_symbol`. The symbol SHALL be resolved by
`symbol_for(underlying, expiry_date, strike, option_type)`, preferring the real symbol and historical
`security_id` from a masters snapshot when available. The warehouse MUST support reading a held
contract as one stable series by the contract key, and SHALL allow lookup by `trading_symbol` or
`security_id` when present.

#### Scenario: Held contract read as a stable series

- **WHEN** a consumer queries `option_bars` for a fixed `(underlying, expiry_date, strike,
  option_type, timeframe)` over a date range
- **THEN** it receives a single contiguous fixed-strike series ordered by `ts` that does not drift
  across strikes as spot moves

#### Scenario: Symbol resolved for a contract lacking one

- **WHEN** a bar is written for a contract whose source has no trading symbol
- **THEN** `symbol_for(...)` supplies the canonical Dhan trading symbol
- **AND** when a masters snapshot covers the contract, the real symbol and `security_id` are used
