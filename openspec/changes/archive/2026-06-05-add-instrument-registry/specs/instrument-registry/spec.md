## ADDED Requirements

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
