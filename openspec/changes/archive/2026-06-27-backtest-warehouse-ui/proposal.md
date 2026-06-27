## Why

The directional-strangle work now produces real, decision-grade output: a full 5-year run
(naked + hedged) and a walk-forward optimizer that emits per-fold IS/OOS metrics and a
PASS/REVIEW verdict. Today those results live **only as files** under `backtest/runs/<id>/`
(`manifest.json`, `summary.csv`, `equity.csv`, `days/<date>/…`). They are reproducible but not
queryable: there is no way to list runs, filter by metric, compare two runs' equity curves, drill
into a single day's every-minute trace from a browser, launch an optimization sweep, or govern
which config gets promoted to paper. The existing `/api/v1/backtests` REST API and `BacktestRun`
Postgres tables are wired to the **older options-replay engine**, not the strangle/walk-forward
pipeline, so they cannot serve this.

To run the strategy lifecycle with confidence — backtest → tune → compare → promote — the results
must land in a **queryable store** and a **management UI**, and promotion to paper must be a
**governed, PASS-gated action** rather than a manual file copy.

## What Changes

- New **MongoDB backtest warehouse** (per non-negotiable #8: Mongo = bulky time-series/document
  data): collections `backtest_runs`, `backtest_days`, `backtest_folds`, `backtest_trades`. The
  filesystem `backtest/runs/<id>/` tree remains the durable raw record; Mongo is the queryable index.
- New **ingestion**: an idempotent `scripts/ingest_backtest_run.py` that upserts an existing run
  folder into Mongo (lets us load runs already produced), plus a `--mongo` dual-sink flag on the
  `RunWriter` and walk-forward so future runs persist natively.
- New **Mongo-backed read API** under `/api/v1/strangle-backtests`: list/filter/sort runs by any
  headline metric, run detail, equity curve, per-day series, walk-forward folds, day-level trade
  drill-down, and multi-run compare. Each endpoint does one thing (non-negotiable #3).
- New **launch/optimize API**: submit a single backtest, a grid sweep, or a walk-forward through
  the existing async **job runner**, with WS progress; results land in the warehouse on completion.
- New **frontend backtest console** at `/backtest`: runs table (sortable/filterable by PF, Sharpe,
  maxDD, net; kind + PASS/REVIEW + promotion badges), run detail (equity + drawdown + per-day P&L
  + metric cards + config viewer), an interactive **walk-forward view** (per-fold IS-vs-OOS table +
  stitched-OOS equity + verdict), **day drill-down** (every-minute status trace + trades + legs),
  a **compare** view (overlaid equity curves), an **optimize** panel (launch sweep/walk-forward,
  live progress, OOS leaderboard), and a **promotion** workflow.
- New **PASS-gated promotion**: only a walk-forward run whose verdict is PASS is promotable;
  promotion generates `strategies/<id>.yaml` (paper-first, `LIVE` unset) and records an auditable
  promotion document. This closes the loop into `StrategyHost` auto-load.

## Capabilities

### New Capabilities
- `backtest-warehouse`: Mongo persistence of backtest/sweep/walk-forward results, a read +
  launch/optimize API, a management UI, and a PASS-gated promotion workflow.

### Modified Capabilities
- None change behavior. The new API lives under a distinct `/api/v1/strangle-backtests` prefix and
  the new collections are additive; the legacy options-replay `/api/v1/backtests` Postgres path is
  untouched.

## Impact

- New `src/pdp/backtest/store.py` — `BacktestStore` (Mongo upsert/query) + collection init in
  `src/pdp/mongo/collections.py`.
- New `src/pdp/backtest/warehouse_routes.py` — `/api/v1/strangle-backtests` read + launch + promote.
- New `scripts/ingest_backtest_run.py` — folder → Mongo idempotent ingest.
- Modify `src/pdp/backtest/strangle_report.py` (RunWriter) + `backtest/strangle_run.py` +
  `backtest/strangle_walkforward.py` — optional `--mongo` dual-sink.
- New frontend: expand `frontend/src/routes/backtest.tsx` + components (runs table, run detail,
  walk-forward view, day drill-down, compare, optimize, promote); TanStack Query hooks.
- New `frontend/e2e/` Playwright specs for the console routes (non-negotiable #10).
- New `src/pdp/strategy/promotion.py` (or extend `StrategyHost`) — generate strategy YAML from a
  promoted config + write the promotion record.
- Reuse the async **job runner** (`src/pdp/jobs/`) and its WS progress; reuse `RunWriter` artifacts.
- No new external dependencies. No new Postgres tables (all new persistence is Mongo).
