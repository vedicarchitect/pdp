# historical-data-migration Specification

## Purpose

Defines the data pipeline that populates `option_bars` and `market_bars` with historical NIFTY
options and spot data from Dhan, and keeps it fresh via self-healing gap backfill. The one-time
seeding migrations (archived scripts) are complete; this spec now governs ongoing gap-fill and
validation only.

## Requirements

### Requirement: Dhan gap-fill to the present

The system SHALL provide a gap-fill command covering any date range up to the present, upserting
into `option_bars`. Recent contracts still resolvable in the instruments table MUST be fetched by
`security_id`; truly expired contracts MUST be fetched via the Dhan rolling-option API with the
expiry calendar assigning `expiry_date` and `strike`. The command MUST be idempotent.

#### Scenario: Gap range filled idempotently

- **WHEN** the gap-fill runs for a date range
- **THEN** missing bars are upserted into `option_bars`
- **AND** a second run inserts zero new documents

### Requirement: NIFTY spot backfill

The system SHALL provide a command that backfills NIFTY (and BANKNIFTY/SENSEX) index 1-minute bars
into `market_bars` from Dhan, deduplicated by `ts`, idempotent with `--only-missing`.

#### Scenario: Spot history available

- **WHEN** the spot backfill runs
- **THEN** `market_bars` contains index 1-minute bars over the source range with no duplicate `ts`

### Requirement: Warehouse validation gates

The system SHALL provide a validation command that fails (non-zero exit) on any integrity breach:
timestamp coverage, OHLC sanity (`high≥low`, `high≥max(open,close)`, `low≤min(open,close)`),
non-null/positive `strike` and `close`, zero duplicate `(contract, ts)`, `expiry_date` plausibility
(every bar `ts.date ≤ expiry_date`), and `strike_label`↔`strike` consistency.

#### Scenario: Validation passes on a clean warehouse

- **WHEN** the validation runs against a correctly populated warehouse
- **THEN** all gates pass and the command exits zero

#### Scenario: Validation fails on an integrity breach

- **WHEN** any gate detects a breach (e.g. a bar dated after its `expiry_date`)
- **THEN** the command logs the failing gate and exits non-zero
