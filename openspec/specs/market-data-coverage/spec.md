# market-data-coverage Specification

## Purpose
TBD - created by archiving change market-data-coverage. Update Purpose after archive.
## Requirements
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
`pdp/backtest/completeness.py` to a per-family check. The radar SHALL cover only input families
that have a real ingested source and are actually consumed by the strategy: `spot`, `options`,
`vix`, and `levels_weekly`. It SHALL NOT report a `futures` family — futures are not warehoused
and, since VWAP is no longer a bias input, nothing consumes them, so the perpetual
"futures missing" flag is removed rather than emitted as noise. A missing or incomplete family
SHALL be reported with a human-readable label — e.g. "spot missing", "weekly Camarilla missing"
(prior-week spot or `index_levels` gap), "VIX missing" — so the console can render one row per
(index, date, family) with a status.

#### Scenario: A missing input family is flagged
- **WHEN** a trade-date lacks the prior-week spot needed for weekly Camarilla
- **THEN** the radar reports that (index, date) as "weekly Camarilla missing"

#### Scenario: A ready date reports all families present
- **WHEN** a trade-date has complete spot, options, VIX, and levels
- **THEN** the radar reports all families ready for that (index, date)

#### Scenario: No futures family is reported

- **WHEN** the gap radar output is produced for any (index, date)
- **THEN** it contains no `futures` family key and never emits a "futures missing" label

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

### Requirement: Per-expiry option-chain coverage

The coverage system SHALL report option-chain completeness per `(underlying, expiry_date)`,
not only per trading day. For each underlying it SHALL group `option_bars` by `expiry_date`
and report, for every expiry, whether a complete chain exists (strikes/contracts present
across the expected range) or a gap, so that a phantom expiry (claimed but with no stored
chain) or a real expiry with a missing chain is surfaced rather than hidden behind a per-day
aggregate.

#### Scenario: A claimed expiry with no chain is flagged

- **WHEN** per-expiry coverage is computed for an underlying
- **AND** an expiry is claimed upstream but no `option_bars` chain exists for it
- **THEN** that expiry is reported as missing/gapped in the per-expiry coverage breakdown

#### Scenario: A real expiry with a partial chain is flagged

- **WHEN** per-expiry coverage is computed for an underlying
- **AND** an expiry has some but not the full expected strike coverage
- **THEN** that expiry is reported as a partial/gap chain, distinct from a complete one

#### Scenario: Per-expiry breakdown is exposed via the coverage API and audit script

- **WHEN** the coverage API (or `scripts/audit_options_coverage.py`) is queried for an
  underlying
- **THEN** the response includes a per-expiry breakdown listing each expiry with its
  complete-vs-gap status

