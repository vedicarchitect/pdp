## ADDED Requirements

### Requirement: Backtest run persistence to MongoDB
The system SHALL persist every strangle backtest, grid sweep, and walk-forward run to MongoDB in a
`backtest_runs` collection, with one document per run keyed by the run id, capturing the run kind
(`single` | `sweep` | `walkforward`), strategy id, the full resolved config, the date window,
headline metrics (net, profit-factor, win rate, max drawdown, Sharpe, Calmar, trades, halted days),
the git sha, a `status`, a `promotion_state`, and a created-at timestamp. The filesystem
`backtest/runs/<id>/` tree SHALL remain the durable raw record; Mongo SHALL be the queryable index.

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
runs produced before this feature can be loaded without re-running them.

#### Scenario: An existing folder is ingested
- **WHEN** the ingest command is run against an existing run folder
- **THEN** the run, its per-day rows, and any folds are upserted into Mongo and the run appears in the list API

### Requirement: Native dual-sink persistence
The run writer and walk-forward optimizer SHALL support persisting to Mongo at run time behind an
opt-in flag, writing the same documents the ingestion path produces, so future runs are warehoused
without a separate ingest step. Filesystem artifacts SHALL still be written.

#### Scenario: A run persists natively when the flag is set
- **WHEN** a backtest is run with Mongo persistence enabled
- **THEN** both the filesystem artifacts and the `backtest_runs`/`backtest_days` documents are written by the run itself

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
The frontend SHALL provide a backtest console that lists runs in a sortable, filterable table
(profit-factor, Sharpe, max drawdown, net, kind, PASS/REVIEW, promotion status), a run-detail view
with equity and drawdown charts, per-day P&L, metric cards, and a config viewer, an interactive
walk-forward view showing per-fold IS-vs-OOS metrics with the stitched-OOS curve and verdict, a
day drill-down showing the every-minute status trace with trades and legs, and a compare view that
overlays multiple runs' equity curves. New routes and components SHALL be covered by Playwright e2e
tests.

#### Scenario: A user inspects a walk-forward run
- **WHEN** a user opens a walk-forward run in the console
- **THEN** the per-fold IS-vs-OOS table, the stitched-OOS equity curve, and the PASS/REVIEW verdict are displayed

#### Scenario: A user compares two runs
- **WHEN** a user selects two runs to compare
- **THEN** their equity curves are overlaid and headline metrics shown side by side

### Requirement: In-UI optimization and leaderboard
The frontend SHALL let a user launch a sweep or walk-forward from the console (choosing window,
objective, and grid), track its progress live, and view an out-of-sample leaderboard ranking
configs by a chosen metric.

#### Scenario: A user launches and tracks an optimization
- **WHEN** a user starts a walk-forward from the UI
- **THEN** progress is shown live and, on completion, the run appears in the runs table and the OOS leaderboard

### Requirement: PASS-gated promotion to paper
The system SHALL allow promoting a configuration to a paper strategy only when it originates from a
walk-forward run whose verdict is PASS; promotion SHALL generate a strategy YAML under `strategies/`
(paper-first, with no live flag), record an auditable promotion document (source run id, verdict,
config, actor, timestamp) in Mongo, and update the source run's `promotion_state`. A non-PASS run
SHALL NOT be promotable.

#### Scenario: A PASS run is promoted
- **WHEN** a user promotes a walk-forward run whose verdict is PASS
- **THEN** a paper-first strategy YAML is written under `strategies/`, a promotion document is recorded, and the run's promotion state becomes promoted

#### Scenario: A REVIEW run cannot be promoted
- **WHEN** a user attempts to promote a run whose verdict is REVIEW
- **THEN** the promotion is rejected and no strategy YAML or promotion document is written
