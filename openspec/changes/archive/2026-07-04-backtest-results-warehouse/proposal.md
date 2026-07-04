## Why

Our strategy stands on top of exhaustive backtest results and insights, but today those results
are half-captured: parameter sweeps are a silent no-op, there is no persisted leaderboard / best
param, promotion-to-paper records only the word `PASS` with no evidence, and the rich
minute-by-minute decision trace (why we entered, scaled, rolled, or exited) is written to
throwaway local files instead of the DB. We cannot answer "why did the strategy do X on this
minute" from the database, and we cannot show or reproduce the ₹1.15 Cr NIFTY / ₹35L BANKNIFTY
track record that currently only exists as git-ignored `backtest/runs/` folders. This change makes
the DB the single source of truth for backtest results and their full reasoning.

## What Changes

- **Real parameter sweeps**: `backtest_sweep_handler` executes the grid (currently ignores it),
  reusing the existing grid/ranking logic from `backtest/run.py` + `backtest/sweep_all.py`.
- **Persisted sweep leaderboard**: a new `backtest_sweeps` store — sweep_id, param grid, every
  combo's metrics, ranking, and the selected `best_param`.
- **Self-contained promotion rationale**: promotion records an evidence snapshot (stitched-OOS
  metrics, per-threshold PASS/actual breakdown, fold win-rate, source-run link) plus an optional
  operator note — not just `verdict`. Verdict thresholds are centralized (today duplicated).
- **DB-first results, no local files** *(BREAKING for run output)*: new runs write results straight
  to Mongo and route all logs to OpenSearch; the local-folder archival (`RunWriter`), `logs/*.log`,
  and `wf.csv` outputs are deprecated. Existing local `backtest/runs/*` + `logs/*` become a
  one-time import source: ingest, verify in DB, then remove.
- **Decision trace in the DB**: a new strategy-agnostic `backtest_decisions` event stream. By
  default it stores the discrete decision events with reason codes (`st_flip`, `entry`, `scale_in`,
  `rollup(premium_decay)`, `exit(tp|stop|flip|squareoff)`, `reentry(cooloff_15m)`) plus the
  indicator/bias snapshot *at those moments* and per-day summaries — so "why entry / why exit" is
  answerable for any strategy/params without heavy storage. The **full per-minute snapshot** (every
  bar, incl. quiet minutes) is materialized **on demand** for a specific run+date when requested,
  not stored for every run/sweep combo.
- **Ingest the existing track record**: bulk-ingest the ~33 local runs (incl. the ₹1.15 Cr NIFTY +
  ₹35L BANKNIFTY runs) so the warehouse shows the real history immediately.
- **OpenSearch**: add `sweep_id`/`param_grid` to the `backtest-runs` mapping, a promotion-event
  sink, and a `backtest-decisions` family + dashboard.

## Capabilities

### New Capabilities
- `backtest-sweeps`: real grid-sweep execution plus a persisted leaderboard of every combo's
  metrics, ranking, and the selected best param.
- `backtest-decision-trace`: a strategy-agnostic, per-minute decision-event store (indicator/bias
  snapshot + typed reason-coded actions) persisted to the DB and OpenSearch, answering why entry /
  why exit for any run.

### Modified Capabilities
- `backtest-warehouse`: results become DB-first with **no local files** (logs to OpenSearch);
  promotion records a self-contained evidence snapshot + optional note; runs carry full `config`/
  `params`; add ingest-then-remove retention for legacy local runs. (The stale Playwright reference
  in that spec's UI requirement is fixed in change 5, which owns the UI.)

## Impact

- Backend: `pdp/backtest/job_handlers.py`, `pdp/backtest/store.py`, `pdp/backtest/strangle_report.py`
  (deprecate local writer), `pdp/backtest/strangle_sim.py` (emit decision events),
  `pdp/backtest/warehouse_routes.py`, `pdp/strategy/promotion.py`, `pdp/mongo/collections.py`,
  `pdp/observability/{mappings,sinks}.py`, `backtest/run.py`, `backtest/sweep_all.py`,
  `backtest/strangle_walkforward.py`, `scripts/ingest_backtest_run.py`.
- New Mongo collections: `backtest_sweeps`, `backtest_decisions`. New OpenSearch families:
  `backtest-decisions` (+ `sweep_id`/`param_grid` on `backtest-runs`, a promotion event).
- New/changed APIs under `/api/v1/strangle-backtests`: sweep leaderboard, promotion rationale,
  decision-trace query.
- Operational logging shifts from local files to OpenSearch; `backtest/runs/` + `logs/*` are
  removed after verified ingest.
- New skills: `/backtest:run`, `/backtest:sweep`, `/backtest:promote`, `/backtest:ingest`,
  `/backtest:explain`.
