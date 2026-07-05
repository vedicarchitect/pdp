## ADDED Requirements

### Requirement: Per-underlying, per-family coverage API
The system SHALL expose `GET /api/v1/coverage` that returns, for each configured underlying
(NIFTY, BANKNIFTY, SENSEX) and each market-data family (spot bars, options chain, India VIX,
`index_levels` daily/weekly Camarilla, futures), the earliest and latest available date, the count
of covered trade-days, the gap-day ranges within a requested window, and a coverage percentage. The
computation SHALL reuse the existing gap-detection helpers (`gap_backfill.days_missing`,
`expected_contracts`, `trading_days`) rather than a parallel implementation.

#### Scenario: Coverage is reported per underlying and family
- **WHEN** the coverage endpoint is requested for a date window
- **THEN** for each underlying and family it returns min/max date, covered trade-day count, gap-day ranges, and coverage %

#### Scenario: Coverage spans all three indices
- **WHEN** the coverage endpoint is requested
- **THEN** NIFTY, BANKNIFTY, and SENSEX are all represented (not NIFTY-only)

### Requirement: Input-family gap radar
The system SHALL expose a gap radar that assesses, per (underlying, trade-date), the readiness of
each input family the backtest depends on, promoting the spot-completeness gate in
`pdp/backtest/completeness.py` to a per-family check. A missing or incomplete family SHALL be
reported with a human-readable label — e.g. "spot/VWAP missing" (spot gap), "weekly Camarilla
missing" (prior-week spot or `index_levels` gap), "VIX missing", "futures missing" — so the console
can render one row per (index, date, family) with a status.

#### Scenario: A missing input family is flagged
- **WHEN** a trade-date lacks the prior-week spot needed for weekly Camarilla
- **THEN** the radar reports that (index, date) as "weekly Camarilla missing"

#### Scenario: A ready date reports all families present
- **WHEN** a trade-date has complete spot, options, VIX, and levels
- **THEN** the radar reports all families ready for that (index, date)

### Requirement: One-click delta-fill action
The system SHALL let the coverage/gap-radar surface trigger a targeted backfill for a specific
underlying and family through the existing housekeeping job endpoint, using delta semantics
(fill up to today, only-missing). Progress SHALL stream over the existing jobs WebSocket, and a
re-check SHALL reflect the closed gap.

#### Scenario: A gap is delta-filled from the radar
- **WHEN** a one-click backfill is triggered for a (underlying, family) with a gap
- **THEN** a housekeeping job runs for that underlying/family, progress streams over `/ws/jobs`, and a subsequent coverage check shows the gap closed

### Requirement: Coverage snapshots to OpenSearch
The system SHALL route coverage snapshots to a `data-coverage` OpenSearch family (following the
existing indexer/mapping/sink convention) and provide a coverage dashboard loaded by
`task search:init`, so data health is trackable over time alongside the other dashboards.

#### Scenario: Coverage is queryable in OpenSearch
- **WHEN** a coverage snapshot is produced
- **THEN** it is indexed under `data-coverage` with underlying, family, date, coverage %, and gap counts, and appears on the coverage dashboard
