## ADDED Requirements

### Requirement: Backfill refuses to persist interior gaps
The system SHALL NOT persist a backfilled day when a chunk returns zero candles but chunks both
before and after it within the same day contain data; it SHALL retry and, on continued failure,
leave the day unwritten.

#### Scenario: Interior empty chunk is treated as flakiness
- **WHEN** intraday chunks for a day are fetched and an empty chunk falls strictly between two
  non-empty chunks
- **THEN** the empty chunks are retried
- **AND** if they remain empty the day is not written and a `backfill_interior_gap` event is logged

#### Scenario: Genuinely empty window is allowed
- **WHEN** a day's chunks are empty with no data on either side of the empty region (e.g. a holiday
  or a contract with no trades)
- **THEN** this is not treated as an interior gap and does not raise an error

#### Scenario: Unwritten day remains visible to the gap scan
- **WHEN** a day is left unwritten due to an interior gap
- **THEN** the existing gap scan re-detects the day as missing on its next run

---

### Requirement: Scheduled scrip-master refresh
The system SHALL refresh the Dhan scrip master on a daily pre-open schedule when enabled, recording
changes to lot size, expiry, and freeze quantity.

#### Scenario: Daily refresh records changes
- **WHEN** `SCRIP_REFRESH_ENABLED` is true and the scheduled refresh time is reached
- **THEN** the loader re-downloads and upserts the master
- **AND** changes to `lot_size`, `expiry`, or `freeze_qty` are recorded via the snapshots module

#### Scenario: Refresh failure retains last-good data
- **WHEN** the scheduled refresh download fails
- **THEN** the error is logged, the last-good master is retained, and startup is not affected
