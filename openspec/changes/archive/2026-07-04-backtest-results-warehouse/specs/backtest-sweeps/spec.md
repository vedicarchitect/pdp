## ADDED Requirements

### Requirement: Real grid-sweep execution
The system SHALL execute a parameter sweep by expanding the requested parameter grid into its
combinations, running a backtest for each combination over the requested window, and collecting each
combination's headline metrics. The async sweep job handler SHALL run the actual grid — it SHALL NOT
silently fall back to a single default config. Grid expansion and per-combination ranking SHALL
reuse the existing sweep logic (`backtest/run.py`, `backtest/sweep_all.py`) rather than a parallel
implementation.

#### Scenario: A sweep runs every grid combination
- **WHEN** a sweep is launched with a grid of N parameter combinations over a date window
- **THEN** N backtests are executed, one per combination, and each combination's headline metrics are recorded

#### Scenario: An empty or missing grid is rejected
- **WHEN** a sweep is launched with no parameter grid
- **THEN** the job fails with a clear error rather than running a single default config

### Requirement: Persisted sweep leaderboard
The system SHALL persist each sweep to a `backtest_sweeps` collection keyed by a sweep id, holding
the parameter grid, the date window, and a ranked list of every combination with its resolved params
and headline metrics, together with the selected `best_param` (the top-ranked combination by the
sweep's objective metric). The leaderboard SHALL be reconstructable from the DB without re-running
the sweep.

#### Scenario: The leaderboard is persisted and ranked
- **WHEN** a sweep completes
- **THEN** a `backtest_sweeps` document exists with every combination's params and metrics ranked by the objective, and `best_param` set to the top combination

#### Scenario: Re-persisting the same sweep is idempotent
- **WHEN** the same sweep id is persisted twice
- **THEN** the existing `backtest_sweeps` document is upserted in place rather than duplicated

### Requirement: Sweep leaderboard read API
The system SHALL expose a Mongo-backed endpoint under `/api/v1/strangle-backtests` that returns a
sweep's leaderboard — the ranked combinations with their params and metrics and the selected
`best_param` — for a given sweep id.

#### Scenario: A sweep leaderboard is fetched
- **WHEN** the sweep leaderboard endpoint is requested for a sweep id
- **THEN** the ranked combinations, their params and metrics, and the `best_param` are returned

### Requirement: Sweep runs indexed to OpenSearch
The system SHALL record `sweep_id` and the parameter grid on the OpenSearch `backtest-runs`
documents so sweep combinations are queryable and rankable in the observability layer alongside
single and walk-forward runs.

#### Scenario: Sweep combinations are queryable in OpenSearch
- **WHEN** a sweep's combinations are indexed
- **THEN** each carries its `sweep_id` and grid, and can be aggregated/ranked by metric in the backtest dashboards
