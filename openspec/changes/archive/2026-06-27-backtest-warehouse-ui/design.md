# Design — backtest-warehouse-ui

## Storage: why MongoDB, not Postgres

Per non-negotiable #8 the database split is: **Postgres = orders/trades/positions (ACID)**,
**Mongo = bars/chains (bulky time-series/document data)**, Redis = hot cache. Backtest run output is
document-shaped, append-only, and bulky (per-day series, per-minute traces, per-fold metrics, full
nested config). It is not transactional ledger data. It therefore belongs in Mongo, alongside the
existing `market_bars` / `option_bars` collections, and reuses the established Mongo client and
collection-init pattern. The legacy options-replay `BacktestRun` Postgres tables and their
`/api/v1/backtests` API are **left untouched**; this feature lives under a separate API prefix and
separate collections so there is no migration and no behavior change to existing capabilities.

## Filesystem stays the source of truth

`backtest/runs/<id>/` (manifest.json + summary.csv + equity.csv + days/<date>/…) remains the durable,
reproducible raw record and stays git-ignored. Mongo is a **queryable index** derived from it. This
keeps two properties: (1) a run can always be re-ingested from disk if a collection is dropped, and
(2) the warehouse never becomes a single point of data loss. Ingestion is therefore idempotent
upsert keyed by run id, so re-ingesting is safe and repeatable.

## Collections

| Collection | Key | Shape |
|---|---|---|
| `backtest_runs` | `run_id` | kind, strategy_id, config (nested), window, metrics, git_sha, status, promotion_state, created_at |
| `backtest_days` | `(run_id, date)` | day_pnl, trades, equity, peak, drawdown, build_ms, sim_ms |
| `backtest_folds` | `(run_id, fold_index)` | is_window, oos_window, pick_label, is_metrics, oos_metrics |
| `backtest_trades` | `(run_id, date)` bucket | array of fills (time, side, opt_type, strike, qty, price, leg_pnl, day_pnl) |

`backtest_days` is a natural time-series collection (one row/day); `backtest_trades` is bucketed by
day to keep documents bounded. Indexes: `backtest_runs` on `{kind, created_at}` and on the sort
metrics; `backtest_days`/`backtest_folds`/`backtest_trades` on `run_id`.

## Ingestion vs native dual-sink

Two write paths producing **the same documents**:
- **Ingest script** (`scripts/ingest_backtest_run.py`) — reads an existing run folder and upserts.
  This is the non-invasive path and is how the runs already produced (the 5-year naked/hedged and the
  walk-forward) get loaded without re-running them.
- **Native dual-sink** — a `--mongo` flag on `RunWriter` and the walk-forward writes the same
  documents at run time. Implemented by extracting the document-building from the ingest script into
  a shared `BacktestStore` so both paths are identical and cannot drift.

## API surface (one mutation/route)

`/api/v1/strangle-backtests` — read: `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/equity`,
`GET /runs/{id}/days`, `GET /runs/{id}/folds`, `GET /runs/{id}/days/{date}/trades`,
`POST /compare` (read-only aggregation of N ids). Launch: `POST /runs` (single), `POST /sweeps`,
`POST /walkforwards` — each submits one async job and returns a job id; progress reuses the existing
jobs WebSocket. Promotion: `POST /runs/{id}/promote`. Each route does exactly one thing.

## Promotion governance

Promotion is the only path from backtest to paper and must be a gate, not a file copy. The endpoint
SHALL refuse any run whose walk-forward verdict is not PASS. On success it (1) materializes a
`strategies/<id>.yaml` from the run's config with no live flag (paper-first, per non-negotiable #2),
(2) writes a `backtest_promotions` document (source run id, verdict, config snapshot, actor,
timestamp), and (3) flips the source run's `promotion_state`. The generated YAML is what
`StrategyHost` auto-loads, so live == the validated backtest config by construction.

## Frontend

Expand the existing `/backtest` route into a console (TanStack Query hooks against the new API):
runs table → run detail (equity/drawdown/per-day/metrics/config) → walk-forward view (fold table +
stitched OOS + verdict badge) → day drill-down (every-minute trace + trades + legs) → compare
(overlay) → optimize (launch + live progress + OOS leaderboard) → promote (PASS-gated action with
confirmation). Charts use the existing chart theme. Every new route/component gets a Playwright e2e
spec (non-negotiable #10).

## Phasing

MVP = warehouse + read API + view/compare UI (P1–P3); fast-follow = in-UI optimization and
promotion (P4–P5). This makes the 5-year and walk-forward results we already have visualizable
quickly, before adding the heavier launch/promote machinery.

## Out of scope

- No changes to the strangle simulator, bias engine, or walk-forward selection logic (that is the
  `directional-strangle` change).
- No live trading; promotion produces paper-first configs only.
- No migration of the legacy options-replay Postgres backtest tables.
