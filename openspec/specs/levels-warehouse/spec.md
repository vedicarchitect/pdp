# levels-warehouse Specification

## Purpose

Persisted pivot/price-levels warehouse for NIFTY, BANKNIFTY, and SENSEX. Computes and stores daily and
weekly standard/Camarilla/Fibonacci levels in MongoDB so they are available at session start without
recomputation, backfillable over multi-year history, and consumable by backtests and ML as a keyed
feature source. Reuses the existing pivot math from `pdp.indicators.pivots` — this warehouse is a
persistence layer, not a second pivot implementation.

## Requirements

### Requirement: Persisted pivot/levels warehouse

The system SHALL persist computed price levels in a MongoDB collection `index_levels`, one document per
`(security_id, period, session_date)`, where `period` is `daily` or `weekly`. Each document SHALL
contain `schema_version`, `security_id`, `underlying`, `period`, `session_date` (the session the levels
apply to), a `source` object (`h`, `l`, `c`, `window_start`, `window_end` of the prior session/week),
`standard` (pp/r1/r2/r3/s1/s2/s3), `camarilla` (pp/r3/r4/s3/s4), `fibonacci` (pp/r1/r2/r3/s1/s2/s3), an
open `levels` map reserved for future families, and `computed_at`. The collection SHALL be a regular
(non-time-series) collection with a unique index on `(security_id, period, session_date)` and a
secondary index on `(underlying, period, session_date)`. Writes SHALL be idempotent upserts.

Level math SHALL reuse `pdp.indicators.pivots._compute_pivots`; the warehouse MUST NOT introduce a
second pivot implementation.

#### Scenario: Daily levels stored from prior session HLC

- **WHEN** the daily compute runs for NIFTY with the prior trading day's HLC
- **THEN** `index_levels` contains a `period:"daily"` document for the next trading session with populated `standard`, `camarilla`, and `fibonacci`

#### Scenario: Weekly levels stored from prior week HLC

- **WHEN** the weekly compute runs for an index using the prior ISO-week aggregated HLC
- **THEN** `index_levels` contains a `period:"weekly"` document whose `source.window_start`/`window_end` span that ISO week

#### Scenario: Idempotent re-run

- **WHEN** the compute runs twice for the same `(security_id, period, session_date)`
- **THEN** exactly one document exists for that key (upserted, not duplicated)

### Requirement: Daily levels compute job

The system SHALL compute and persist the current session's daily levels for NIFTY, BANKNIFTY, and SENSEX
at startup and at each new trading-day boundary, and SHALL recompute weekly levels at the start of each
ISO week. The job MUST read source HLC from `market_bars` and MUST NOT block the tick hot path.

#### Scenario: Levels available at session start

- **WHEN** the application starts on a trading day with prior-session bars present in `market_bars`
- **THEN** `index_levels` has daily documents for NIFTY, BANKNIFTY, and SENSEX for that session

### Requirement: Five-year levels backfill

The system SHALL provide `scripts/backfill_levels.py`, runnable as `task backfill:levels`, that
backfills daily and weekly levels for NIFTY/BANKNIFTY/SENSEX from spot `market_bars` over a configurable
range (supporting at least five years), with `--symbol`, `--from`, `--to`, `--only-missing`, and
`--dry-run` flags. It SHALL reuse `trading_days()`/`holidays()` from `pdp.options.gap_backfill` and write
idempotently.

#### Scenario: Backfill dry run reports plan

- **WHEN** `task backfill:levels -- --symbol NIFTY --from 2021-06-30 --dry-run` is run
- **THEN** it logs the trading-day count and range without writing to MongoDB

#### Scenario: Backfill populates daily and weekly

- **WHEN** the backfill runs for SENSEX over a multi-year range
- **THEN** `index_levels` contains both `daily` and `weekly` documents for security_id 51 across that range

### Requirement: Levels read API and ML access

The system SHALL expose `GET /api/v1/levels/{underlying}` accepting `period` and `date` (plus a range
form) returning the stored level document(s). `LevelsStore` SHALL provide `range(security_id, period,
start, end)` and `to_feature_rows()` (flattened columns) so backtests and ML can consume levels as a
feature source keyed by `session_date`.

#### Scenario: Read a stored daily level

- **WHEN** `GET /api/v1/levels/NIFTY?period=daily&date=2026-06-30` is called and that document exists
- **THEN** the response is HTTP 200 with the stored `standard`/`camarilla`/`fibonacci` levels

#### Scenario: Range feed for ML

- **WHEN** `LevelsStore.range("13","daily",start,end)` is called
- **THEN** it returns the daily documents in `[start, end]` ordered by `session_date`
