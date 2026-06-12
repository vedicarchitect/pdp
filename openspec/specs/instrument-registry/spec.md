# instrument-registry Specification

## Purpose
TBD - created by archiving change add-instrument-registry. Update Purpose after archive.
## Requirements
### Requirement: Instrument master ingest

The system SHALL fetch Dhan's `api-scrip-master-detailed.csv` and upsert all rows into the `instruments` table, keyed by `(security_id, exchange_segment)`. Each row SHALL include trading symbol, instrument type, lot size, tick size, expiry (if applicable), strike (if applicable), option type (if applicable), underlying, and ISIN.

#### Scenario: Refresh populates instruments

- **WHEN** `pdp instruments refresh` is run against an empty database
- **THEN** the `instruments` table is populated with > 100,000 rows
- **AND** log output reports `added`, `updated`, `unchanged` counts

#### Scenario: Refresh is idempotent

- **WHEN** `pdp instruments refresh` is run twice in succession
- **THEN** the second run reports `added = 0` and `updated <= total` (only changed rows touched)

### Requirement: Instrument search endpoint

The system SHALL expose `GET /api/v1/instruments` accepting optional `q`, `segment`, `instrument_type`, `underlying`, `expiry` query parameters and returning up to 20 matching instruments.

#### Scenario: Search by symbol prefix

- **WHEN** `GET /api/v1/instruments?q=NIFTY&segment=NSE_FNO` is called
- **THEN** the response is HTTP 200 with a JSON array of up to 20 instruments where `trading_symbol` or `underlying` matches `NIFTY` and `exchange_segment = "NSE_FNO"`
- **AND** results are ordered by exact-match first, then prefix-match, then contains

#### Scenario: Empty query returns recent

- **WHEN** `GET /api/v1/instruments` is called with no `q`
- **THEN** the response is HTTP 200 with the 20 most-recently-updated instruments

### Requirement: Instrument detail endpoint

The system SHALL expose `GET /api/v1/instruments/{security_id}?segment={segment}` returning a single instrument or 404.

#### Scenario: Existing instrument

- **WHEN** the security_id + segment combination exists
- **THEN** the response is HTTP 200 with the full instrument record

#### Scenario: Missing instrument

- **WHEN** the security_id + segment combination does not exist
- **THEN** the response is HTTP 404 with `{"detail": "instrument not found"}`

---

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

---

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

