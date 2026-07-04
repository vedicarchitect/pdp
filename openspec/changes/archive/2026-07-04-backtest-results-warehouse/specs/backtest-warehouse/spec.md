## ADDED Requirements

### Requirement: DB-first results with no local files
The system SHALL treat the database as the single source of truth for backtest results: a run's
`backtest_runs`, `backtest_days`, `backtest_folds`, `backtest_trades`, and decision events SHALL be
written directly to Mongo at run time, and all run logs SHALL be routed to OpenSearch. The system
SHALL NOT write local result artifacts (`backtest/runs/<id>/` folders, `logs/*.log`, `wf.csv`) for
new runs. Everything a user needs to inspect a run — metrics, per-day series, folds, trades, and the
decision trace — SHALL be reconstructable from the DB alone.

#### Scenario: A new run writes no local files
- **WHEN** a backtest is run after this change
- **THEN** its results are persisted to Mongo and its logs to OpenSearch, and no local `backtest/runs/` folder or `.log`/`wf.csv` file is written

#### Scenario: A run is fully inspectable from the DB
- **WHEN** a persisted run is opened
- **THEN** its metrics, per-day equity/drawdown, folds, trades, and decision events are all served from the DB without reading the filesystem

## MODIFIED Requirements

### Requirement: Backtest run persistence to MongoDB
The system SHALL persist every strangle backtest, grid sweep, and walk-forward run to MongoDB in a
`backtest_runs` collection, with one document per run keyed by the run id, capturing the run kind
(`single` | `sweep` | `walkforward`), strategy id, the full resolved config, the date window,
headline metrics (net, profit-factor, win rate, max drawdown, Sharpe, Calmar, trades, halted days),
the git sha, a `status`, a `promotion_state`, and a created-at timestamp. MongoDB SHALL be the
single source of truth for the run record; the system SHALL NOT depend on a durable filesystem
`backtest/runs/<id>/` tree for new runs.

#### Scenario: A completed run is queryable
- **WHEN** a strangle backtest finishes and is persisted
- **THEN** a `backtest_runs` document exists for its run id with the run kind, config, window, and headline metrics, and it is returned by the list API

#### Scenario: Re-ingesting the same run is idempotent
- **WHEN** the same run id is persisted twice
- **THEN** the existing `backtest_runs` document is upserted in place rather than duplicated

### Requirement: Ingestion of existing run folders
The system SHALL provide an idempotent ingestion path that reads an existing `backtest/runs/<id>/`
folder (manifest, summary, equity, per-day artifacts) and upserts it into the Mongo warehouse, so
runs produced before this feature can be loaded without re-running them. Because the DB is now the
source of truth, ingestion SHALL support an ingest-then-remove retention step: once a run's data is
verified present in Mongo, its local folder MAY be removed. The system SHALL NOT remove a local
folder that has not been verified as ingested.

#### Scenario: An existing folder is ingested
- **WHEN** the ingest command is run against an existing run folder
- **THEN** the run, its per-day rows, and any folds are upserted into Mongo and the run appears in the list API

#### Scenario: A verified run's local folder is removed
- **WHEN** ingestion is run with removal enabled and the run is confirmed present in Mongo
- **THEN** the local run folder is deleted

#### Scenario: An unverified run's local folder is kept
- **WHEN** ingestion cannot confirm the run is fully present in Mongo
- **THEN** the local run folder is left in place and no data is lost

### Requirement: PASS-gated promotion to paper
The system SHALL allow promoting a configuration to a paper strategy only when it originates from a
walk-forward run whose verdict is PASS; promotion SHALL generate a strategy YAML under `strategies/`
(paper-first, with no live flag), and update the source run's `promotion_state`. A non-PASS run
SHALL NOT be promotable. The recorded promotion document SHALL be self-contained: in addition to the
source run id, verdict, config, actor, and timestamp, it SHALL capture the justifying evidence
snapshot — the stitched-OOS metrics, a per-threshold PASS-vs-actual breakdown, and the positive-fold
fraction — and SHALL allow an optional free-text operator note.

#### Scenario: A PASS run is promoted with evidence
- **WHEN** a user promotes a walk-forward run whose verdict is PASS
- **THEN** a paper-first strategy YAML is written under `strategies/`, and a promotion document is recorded that includes the stitched-OOS metrics, the per-threshold PASS-vs-actual breakdown, the positive-fold fraction, and any operator note, and the run's promotion state becomes promoted

#### Scenario: An optional operator note is captured
- **WHEN** a user promotes a PASS run and supplies a note
- **THEN** the note is stored on the promotion document alongside the auto-captured evidence

#### Scenario: A REVIEW run cannot be promoted
- **WHEN** a user attempts to promote a run whose verdict is REVIEW
- **THEN** the promotion is rejected and no strategy YAML or promotion document is written

## REMOVED Requirements

### Requirement: Native dual-sink persistence
**Reason**: Superseded by "DB-first results with no local files" — the system no longer dual-writes
filesystem artifacts alongside Mongo. Persisting to the DB is now the only path for new runs, and
logs go to OpenSearch rather than local files.
**Migration**: Run backtests with DB persistence (now the default, not an opt-in flag); no filesystem
artifacts are produced. Existing `backtest/runs/` folders are loaded via the ingestion path and then
removed once verified in Mongo.
