## MODIFIED Requirements

### Requirement: Batched MongoDB bar persistence

The system SHALL persist closed bars to the `market_bars` MongoDB time-series collection via batched motor `insert_many` writes. The flush trigger SHALL be whichever occurs first: 1 second elapsed since last flush, or 500 documents accumulated. Each document SHALL have `ts` set to the bar's `bar_time` (UTC datetime), `metadata` set to `{"security_id": <str>, "timeframe": <str>}`, and OHLCV/OI fields at the top level. Because MongoDB time-series collections cannot carry a unique index, `insert_many`'s `ordered=False` alone does **not** reject a re-write of an already-stored `(ts, metadata)` bucket; the writer SHALL prevent duplicate bucket writes at the application level (e.g. an idempotency check against buckets already flushed this process lifetime, or a delete-then-insert-per-bucket write path) rather than relying on a DB-level constraint. Any write errors SHALL be logged as warnings with the error count.

#### Scenario: Bar document written within 2 seconds

- **WHEN** a 5m bar closes for security 13 at 09:20:00 UTC
- **THEN** within 2 seconds a document with `ts=09:20:00`, `metadata.security_id="13"`, `metadata.timeframe="5m"` and matching OHLCV values exists in the `market_bars` collection

#### Scenario: Buffer overflow protection

- **WHEN** the unwritten bar buffer exceeds 10,000 documents (MongoDB unavailable)
- **THEN** the oldest documents are dropped and a `bar_writer_overflow` structured log is emitted

#### Scenario: Duplicate bucket write is prevented at the application level

- **WHEN** a `BarClosed` event for a `(security_id, timeframe, bar_time)` bucket that has already been
  written to `market_bars` is enqueued again (e.g. after a process restart re-aggregates a tick
  window, or a session-end flush races a regular boundary-crossing close of the same bucket)
- **THEN** the writer SHALL NOT create a second document for that bucket in `market_bars` — the
  duplicate SHALL be detected and dropped (or reconciled via delete-then-insert) before the write,
  not left to a DB-level unique-index skip that time-series collections cannot provide
