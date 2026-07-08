## MODIFIED Requirements

### Requirement: Persisted pivot/levels warehouse

The system SHALL persist computed price levels in a MongoDB collection `index_levels`, one document per
`(security_id, period, session_date)`, where `period` is `daily`, `weekly`, or `monthly`. Each document
SHALL contain `schema_version`, `security_id`, `underlying`, `period`, `session_date` (the session the
levels apply to), a `source` object (`h`, `l`, `c`, `window_start`, `window_end` of the prior
session/week/month), `standard` (pp/r1/r2/r3/s1/s2/s3), `camarilla` (pp/r3/r4/s3/s4), `fibonacci`
(pp/r1/r2/r3/s1/s2/s3), an open `levels` map reserved for future families, and `computed_at`. The
collection SHALL be a regular (non-time-series) collection with a unique index on
`(security_id, period, session_date)` and a secondary index on `(underlying, period, session_date)`.
Writes SHALL be idempotent upserts.

Level math SHALL reuse `pdp.indicators.pivots._compute_pivots`; the warehouse MUST NOT introduce a
second pivot implementation.

#### Scenario: Daily levels stored from prior session HLC

- **WHEN** the daily compute runs for NIFTY with the prior trading day's HLC
- **THEN** `index_levels` contains a `period:"daily"` document for the next trading session with populated `standard`, `camarilla`, and `fibonacci`

#### Scenario: Weekly levels stored from prior week HLC

- **WHEN** the weekly compute runs for an index using the prior ISO-week aggregated HLC
- **THEN** `index_levels` contains a `period:"weekly"` document whose `source.window_start`/`window_end` span that ISO week

#### Scenario: Monthly levels stored from prior month HLC

- **WHEN** the monthly compute runs for an index using the prior calendar-month aggregated HLC
- **THEN** `index_levels` contains a `period:"monthly"` document whose `source.window_start`/`window_end` span that calendar month and whose `camarilla` is populated

#### Scenario: Idempotent re-run

- **WHEN** the compute runs twice for the same `(security_id, period, session_date)`
- **THEN** exactly one document exists for that key (upserted, not duplicated)

### Requirement: Daily levels compute job

The system SHALL compute and persist the current session's daily levels for NIFTY, BANKNIFTY, and SENSEX
at startup and at each new trading-day boundary, SHALL recompute weekly levels at the start of each
ISO week, and SHALL recompute monthly levels at the start of each calendar month (and whenever the
current session's monthly document is missing). The job MUST read source HLC from `market_bars` and MUST
NOT block the tick hot path.

#### Scenario: Levels available at session start

- **WHEN** the application starts on a trading day with prior-session bars present in `market_bars`
- **THEN** `index_levels` has daily documents for NIFTY, BANKNIFTY, and SENSEX for that session

#### Scenario: Monthly levels available for the current session

- **WHEN** the application starts on a trading day and prior calendar-month bars are present in `market_bars`
- **THEN** `index_levels` has a monthly document for each index for the current session

### Requirement: Levels read API and ML access

The system SHALL expose `GET /api/v1/levels/{underlying}` accepting `period` (`daily`, `weekly`, or
`monthly`) and `date` (plus a range form) returning the stored level document(s). `LevelsStore` SHALL
provide `range(security_id, period, start, end)` and `to_feature_rows()` (flattened columns) so
backtests and ML can consume levels as a feature source keyed by `session_date`.

#### Scenario: Read a stored daily level

- **WHEN** `GET /api/v1/levels/NIFTY?period=daily&date=2026-06-30` is called and that document exists
- **THEN** the response is HTTP 200 with the stored `standard`/`camarilla`/`fibonacci` levels

#### Scenario: Read a stored monthly level

- **WHEN** `GET /api/v1/levels/NIFTY?period=monthly&date=2026-07-01` is called and that document exists
- **THEN** the response is HTTP 200 with the stored monthly `camarilla` levels and `source.h`/`source.l` (PMH/PML)

#### Scenario: Range feed for ML

- **WHEN** `LevelsStore.range("13","daily",start,end)` is called
- **THEN** it returns the daily documents in `[start, end]` ordered by `session_date`
