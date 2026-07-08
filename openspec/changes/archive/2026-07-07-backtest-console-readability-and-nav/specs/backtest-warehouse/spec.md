## MODIFIED Requirements

### Requirement: Backtest run persistence to MongoDB
The system SHALL persist each backtest run to MongoDB with its config, window, headline metrics,
verdict, and promotion state. A top-level `underlying` field SHALL be stored on every run and
sweep document (populated from `config.underlying`) so runs and sweeps can be grouped and filtered
by index without reaching into the nested config. Every run SHALL carry a computed `verdict`
(PASS/REVIEW) — single runs and sweep best-combos SHALL be graded against the same thresholds
(`WF_PASS_NET/PF/SHARPE/POS_FRAC`) walk-forward already uses, so no run persists with a null
verdict. `promotion_state` SHALL remain `none` at creation and change only through the PASS-gated
promotion flow.

#### Scenario: A single run is graded

- **WHEN** a single (non-walk-forward) run is persisted with headline metrics above the pass
  thresholds
- **THEN** its stored `verdict` is `PASS` (or `REVIEW` when below), not null, and its
  `promotion_state` is `none` until it is explicitly promoted

#### Scenario: Every run carries a top-level underlying

- **WHEN** a run or sweep is persisted for a given index
- **THEN** the document has a top-level `underlying` field equal to its `config.underlying`

### Requirement: Backtest read API
The system SHALL expose Mongo-backed read endpoints under `/api/v1/strangle-backtests` to list runs
with filtering and sorting by headline metric, fetch a single run's detail, its equity series, its
per-day series, its walk-forward folds, and a single day's trade drill-down. The list endpoint
SHALL support filtering by `underlying` (index) in addition to `kind`, `strategy_id`, and
`verdict`. The API SHALL expose a per-index leaderboard resource that returns, per underlying, the
best config (from the sweep `best_param` and walk-forward `pick_label`) with its headline metrics,
verdict, and promotion state. Each endpoint SHALL do exactly one thing.

#### Scenario: Runs are listed and sorted by metric
- **WHEN** the list endpoint is requested sorted by out-of-sample profit-factor descending with a kind filter of `walkforward`
- **THEN** only walk-forward runs are returned, ordered by profit-factor descending

#### Scenario: Runs are filtered by index

- **WHEN** the list endpoint is requested with an `underlying` filter of NIFTY
- **THEN** only runs whose top-level `underlying` is NIFTY are returned

#### Scenario: The per-index leaderboard names the best config

- **WHEN** the leaderboard resource is requested
- **THEN** it returns, per index, the best config with its headline metrics, verdict, and
  promotion state
