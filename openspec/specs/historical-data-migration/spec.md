# historical-data-migration Specification

## Purpose
TBD - created by archiving change 2026-06-12-options-backfill. Update Purpose after archive.
## Requirements
### Requirement: Abi DuckDB options migration

The system SHALL provide a command that migrates NIFTY expired-option bars from the abi DuckDB
warehouse (`expired_options_ohlcv`) into `option_bars`. It MUST read the source read-only (never
mutate it), filter to scope (`expiry_flag='WEEK'`, `expiry_code IN (1,2)`, all ATM±10 labels, CE+PE;
monthly optional behind a flag), convert IST timestamps to UTC, resolve each bar's real
`expiry_date` via the expiry calendar and its `trading_symbol` via the symbol resolver, and upsert
into `option_bars` with `source=abi`. The migration MUST be idempotent and restartable.

#### Scenario: Scoped migration populates the warehouse

- **WHEN** the migrator runs over a date range
- **THEN** in-scope rows are upserted into `option_bars` with resolved `expiry_date`, actual
  `strike`, `trading_symbol`, `oi`, and `iv`
- **AND** re-running over the same range inserts zero duplicates

#### Scenario: Dry run reports without writing

- **WHEN** the migrator runs with `--dry-run`
- **THEN** it reports the planned series and row counts and writes nothing

### Requirement: Dhan gap-fill to the present

The system SHALL provide a gap-fill command covering the range after the Abi cutoff up to the
present that is not already captured by the live feed, upserting into `option_bars`. Recent
contracts still resolvable in the instruments table MUST be fetched by `security_id`; truly expired
contracts MUST be fetched via the Dhan rolling-option API with the expiry calendar assigning
`expiry_date` and `strike`. The command MUST be idempotent.

#### Scenario: Gap range filled idempotently

- **WHEN** the gap-fill runs for dates after the Abi cutoff
- **THEN** missing bars are upserted into `option_bars`
- **AND** a second run inserts zero new documents

### Requirement: NIFTY spot migration

The system SHALL provide a command that migrates historical NIFTY index 1-minute bars into
`market_bars` (security_id `13`, timeframe `1m`), deduplicated by `ts`, from the Abi spot tables and
the Dhan spot DuckDB.

#### Scenario: Spot history available locally

- **WHEN** the spot migration runs
- **THEN** `market_bars` contains NIFTY index 1-minute bars over the source range with no duplicate
  `ts`

### Requirement: Warehouse validation gates

The system SHALL provide a validation command that fails (non-zero exit) on any integrity breach:
Abi↔Mongo per-series count reconciliation, timestamp coverage, OHLC sanity
(`high≥low`, `high≥max(open,close)`, `low≤min(open,close)`), non-null/positive `strike` and
`close`, zero duplicate `(contract, ts)`, `expiry_date` plausibility (every bar `ts.date ≤
expiry_date`), `strike_label`↔`strike` consistency, and live↔backfill overlap reconciliation.

#### Scenario: Validation passes on a clean warehouse

- **WHEN** the validation runs against a correctly migrated warehouse
- **THEN** all gates pass and the command exits zero

#### Scenario: Validation fails on an integrity breach

- **WHEN** any gate detects a breach (e.g. a bar dated after its `expiry_date`)
- **THEN** the command logs the failing gate and exits non-zero

