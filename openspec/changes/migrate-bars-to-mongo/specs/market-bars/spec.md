## MODIFIED Requirements

### Requirement: Batched MongoDB bar persistence

The system SHALL persist closed bars to the `market_bars` MongoDB time-series collection via batched motor `insert_many` writes. The flush trigger SHALL be whichever occurs first: 1 second elapsed since last flush, or 500 documents accumulated. Each document SHALL have `ts` set to the bar's `bar_time` (UTC datetime), `metadata` set to `{"security_id": <str>, "timeframe": <str>}`, and OHLCV/OI fields at the top level. `insert_many` SHALL use `ordered=False` so duplicate bars are skipped without aborting the batch; any write errors SHALL be logged as warnings with the error count.

#### Scenario: Bar document written within 2 seconds

- **WHEN** a 5m bar closes for security 13 at 09:20:00 UTC
- **THEN** within 2 seconds a document with `ts=09:20:00`, `metadata.security_id="13"`, `metadata.timeframe="5m"` and matching OHLCV values exists in the `market_bars` collection

#### Scenario: Buffer overflow protection

- **WHEN** the unwritten bar buffer exceeds 10,000 documents (MongoDB unavailable)
- **THEN** the oldest documents are dropped and a `bar_writer_overflow` structured log is emitted

#### Scenario: Duplicate bar silently skipped

- **WHEN** `insert_many` is called with a batch containing a document whose `(ts, metadata)` already exists
- **THEN** the duplicate is skipped, the rest of the batch is written, and a warning is logged with the error count

## MODIFIED Requirements

### Requirement: Historical bars REST endpoint

The system SHALL expose `GET /api/v1/bars/{security_id}?tf=<timeframe>&limit=<n>` returning the `n` most-recent closed bars for the given security and timeframe from the `market_bars` MongoDB collection, ordered by `ts` descending. `limit` SHALL default to 375 and be capped at 2000. The response shape SHALL be identical to the previous TimescaleDB-backed implementation.

#### Scenario: Returns recent bars in order

- **WHEN** `GET /api/v1/bars/13?tf=5m&limit=10` is called and at least 10 documents exist in MongoDB
- **THEN** the response is HTTP 200 with a JSON array of exactly 10 bars ordered newest-first

#### Scenario: Returns empty array when no data

- **WHEN** `GET /api/v1/bars/99999?tf=5m` is called and no documents exist for that security
- **THEN** the response is HTTP 200 with an empty JSON array `[]`

#### Scenario: Invalid timeframe rejected

- **WHEN** `GET /api/v1/bars/13?tf=7m` is called
- **THEN** the response is HTTP 422 with a validation error listing valid timeframes
