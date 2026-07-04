# backtest-warehouse Specification

## Purpose
TBD - created by archiving change backtest-warehouse-ui. Update Purpose after archive.
## Requirements
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

### Requirement: Per-day and equity persistence
The system SHALL persist each run's per-day results to a `backtest_days` collection keyed by
`(run_id, date)`, holding day P&L, trade count, cumulative equity, peak, drawdown, and build/sim
timing, sufficient to reconstruct the equity and drawdown curves without re-running the backtest.

#### Scenario: Equity curve is reconstructable from Mongo
- **WHEN** the equity endpoint is requested for a persisted run
- **THEN** the cumulative-equity and drawdown series are returned from `backtest_days` without reading the filesystem

### Requirement: Walk-forward fold persistence
The system SHALL persist walk-forward folds to a `backtest_folds` collection keyed by
`(run_id, fold_index)`, each holding the IS window, OOS window, the IS-selected config label, and
both the IS and OOS metrics, plus a run-level stitched-OOS summary and the PASS/REVIEW verdict.

#### Scenario: Per-fold IS vs OOS is retrievable
- **WHEN** the folds endpoint is requested for a walk-forward run
- **THEN** every fold's IS and OOS metrics and selected config label are returned, along with the stitched-OOS summary and verdict

### Requirement: Trade drill-down persistence
The system SHALL persist per-fill trade detail to a `backtest_trades` collection keyed by run id and
date so a single day can be inspected at fill granularity. Trade persistence MAY be lazy or sampled
for very large runs, but when present it SHALL be retrievable for any persisted day.

#### Scenario: A day's fills are retrievable
- **WHEN** the day-trades endpoint is requested for a persisted (run, date) that has trade detail
- **THEN** the fills for that day are returned with time, side, option type, strike, qty, price, and per-leg/day P&L

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

### Requirement: Backtest read API
The system SHALL expose Mongo-backed read endpoints under `/api/v1/strangle-backtests` to list runs
with filtering and sorting by headline metric, fetch a single run's detail, its equity series, its
per-day series, its walk-forward folds, and a single day's trade drill-down. Each endpoint SHALL do
exactly one thing.

#### Scenario: Runs are listed and sorted by metric
- **WHEN** the list endpoint is requested sorted by out-of-sample profit-factor descending with a kind filter of `walkforward`
- **THEN** only walk-forward runs are returned, ordered by profit-factor descending

#### Scenario: A run's detail is fetched
- **WHEN** the detail endpoint is requested for a run id
- **THEN** the run's config, window, and headline metrics are returned

### Requirement: Multi-run comparison
The system SHALL expose an endpoint that returns aligned equity curves and headline metrics for a
set of run ids so two or more runs can be compared.

#### Scenario: Two runs are compared
- **WHEN** the compare endpoint is requested with two run ids
- **THEN** both runs' equity series and headline metrics are returned in a single response suitable for overlay

### Requirement: Launch and optimization via the job runner
The system SHALL expose endpoints to launch a single backtest, a grid sweep, or a walk-forward
optimization as asynchronous jobs through the existing job runner, returning a job id and streaming
progress over the existing WebSocket channel; on completion the results SHALL be persisted to the
warehouse and become visible to the read API.

#### Scenario: A walk-forward is launched from the API
- **WHEN** a walk-forward launch is requested with a window and objective
- **THEN** a job id is returned, progress streams over the jobs WebSocket, and on completion the run is queryable via the read API

### Requirement: Backtest management UI
The frontend SHALL provide a Flutter backtest console that lists runs in a sortable, filterable table
(profit-factor, Sharpe, max drawdown, net, kind, PASS/REVIEW, promotion status), a run-detail view
with equity and drawdown charts, per-day P&L, metric cards, and a config viewer, an interactive
walk-forward view showing per-fold IS-vs-OOS metrics with the stitched-OOS curve and verdict, a
day drill-down showing the decision trace (reason-coded why-entry/why-exit events, with the full
per-minute trace on demand) with trades and legs, a paper-comparison view overlaying a run against
paper results, a promotion view showing the rationale/evidence, and a data-coverage/gap-radar panel.
New routes and components SHALL be covered by Flutter widget/integration tests (`flutter analyze &&
flutter test`).

#### Scenario: A user inspects a walk-forward run
- **WHEN** a user opens a walk-forward run in the console
- **THEN** the per-fold IS-vs-OOS table, the stitched-OOS equity curve, and the PASS/REVIEW verdict are displayed

#### Scenario: A user inspects why-entry/why-exit for a day
- **WHEN** a user opens a day drill-down in a run
- **THEN** the reason-coded decision events are shown with trades and legs, and the full per-minute trace can be loaded on demand

### Requirement: In-UI optimization and leaderboard
The frontend SHALL let a user launch a single backtest, sweep, or walk-forward from the console
(choosing a strategy from the registry with an editable param form, window, index, and objective),
track its progress live over the jobs WebSocket, and view an out-of-sample leaderboard ranking
configs by a chosen metric with the selected best param.

#### Scenario: A user launches and tracks an optimization
- **WHEN** a user starts a walk-forward from the UI
- **THEN** progress is shown live and, on completion, the run appears in the runs table and the OOS leaderboard

#### Scenario: A user launches from a strategy picker
- **WHEN** a user selects a strategy from the picker, edits its params, and sets a window and index
- **THEN** the launch uses those params (no raw-JSON box) and the run appears on completion

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

