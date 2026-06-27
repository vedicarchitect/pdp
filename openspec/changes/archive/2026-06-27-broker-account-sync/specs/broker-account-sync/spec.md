## ADDED Requirements

### Requirement: Daily broker record archival
The system SHALL persist every Dhan-reported account record — holdings, positions, funds,
orderbook, tradebook, and ledger — as an immutable daily archive in MongoDB, with one document
per `(account_id, snapshot_date, report_type)`. Re-running a date SHALL overwrite that date's
documents (idempotent), never duplicate them.

#### Scenario: A daily sync archives all report types
- **WHEN** `BrokerSyncService.run_daily` runs for a date with valid Dhan credentials
- **THEN** a `broker_snapshots` document exists for that account+date for each available
  report type, each carrying the captured rows, a row count, and the source method

#### Scenario: Re-running a date is idempotent
- **WHEN** the sync runs twice for the same account and date
- **THEN** the second run overwrites the existing documents and the document count for that
  date is unchanged

### Requirement: Current-state mirror and run audit
The system SHALL maintain a PostgreSQL current-state mirror (`broker_holdings`,
`broker_positions`, `broker_funds`) holding only the latest sync, replaced atomically each run,
and SHALL record every sync attempt in a `broker_sync_run` audit row capturing trigger, status,
per-report counts, timing, and any error.

#### Scenario: Current-state reflects the latest sync only
- **WHEN** a sync completes successfully
- **THEN** `broker_holdings`/`broker_positions`/`broker_funds` contain exactly the rows from
  that sync (prior rows for the account removed) and a `broker_sync_run` row records status `ok`

#### Scenario: Partial failure is recorded, not fatal
- **WHEN** one report API fails but others succeed
- **THEN** the successful reports are still archived and the run is recorded with status
  `partial` and the error, without raising

### Requirement: Credential-gated, read-only operation
The sync SHALL use read-only Dhan APIs and place no orders. When Dhan credentials are absent
the sync SHALL record status `skipped` and log a warning rather than failing.

#### Scenario: No credentials configured
- **WHEN** the sync runs without `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`
- **THEN** it records a `skipped` run and the application continues normally

### Requirement: Auto-EOD and manual triggers
The system SHALL run the daily sync automatically after market close at a configurable IST time
(default 15:45) when enabled, and SHALL also expose a manual trigger via REST
(`POST /api/v1/broker-sync/run`) and a `task` command. The scheduled run SHALL skip if that
day already completed successfully.

#### Scenario: Manual trigger runs an on-demand sync
- **WHEN** `POST /api/v1/broker-sync/run` is called (optionally with a date)
- **THEN** a sync runs for that date and the resulting run record is returned

#### Scenario: Scheduled run is once-per-day
- **WHEN** the EOD scheduler fires and an `ok` run already exists for today
- **THEN** it skips without re-syncing

### Requirement: Historical transactional backfill
The system SHALL provide a one-time backfill that pulls Dhan `trade_history` and `ledger` over
a given date range into the Mongo archive. It SHALL document that holdings, positions, and
funds cannot be backfilled (Dhan reports them only as current state).

#### Scenario: Backfill a date range
- **WHEN** `task broker:backfill -- --from 2025-01-01 --to 2025-03-31` runs
- **THEN** `broker_snapshots` ledger and trades documents exist for the dates with activity in
  that range

### Requirement: Reconciliation against the internal ledger
Each sync SHALL compare broker-reported positions against the platform's internal `positions`
table and record a reconciliation summary on the run, logging each mismatch.

#### Scenario: Mismatch is flagged
- **WHEN** a broker position quantity differs from the internal ledger for the same instrument
- **THEN** the run records a reconciliation summary and a `broker_recon_mismatch` log line is
  emitted for that instrument
