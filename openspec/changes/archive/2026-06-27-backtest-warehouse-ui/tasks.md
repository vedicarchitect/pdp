## 1. Mongo warehouse + ingestion (P1)

- [x] 1.1 Add `backtest_runs`, `backtest_days`, `backtest_folds`, `backtest_trades` to `src/pdp/mongo/collections.py` with indexes (`{kind, created_at}` + sort metrics on runs; `run_id` on the rest)
- [x] 1.2 Create `src/pdp/backtest/store.py` (`BacktestStore`) — document builders + idempotent upsert (keyed by run id) + query helpers; single source of the document shape
- [x] 1.3 Create `scripts/ingest_backtest_run.py` — read a `backtest/runs/<id>/` folder → `BacktestStore` upsert; `task backtest:ingest` target
- [ ] 1.4 Ingest the runs already produced (5-year naked, 5-year hedged, walk-forward folds) and confirm they appear via a Mongo query
- [x] 1.5 Add `--mongo` dual-sink to `RunWriter` (`strangle_report.py`) and `strangle_walkforward.py`, writing the identical documents via `BacktestStore`
- [x] 1.6 Unit tests for `BacktestStore` (build + idempotent upsert) and an ingest round-trip test

## 2. Read API (P2)

- [x] 2.1 Create `src/pdp/backtest/warehouse_routes.py` (`/api/v1/strangle-backtests`); wire into the app factory
- [x] 2.2 `GET /runs` — list with filter (kind, strategy, date, metric thresholds) + sort by headline metric + pagination
- [x] 2.3 `GET /runs/{id}`, `GET /runs/{id}/equity`, `GET /runs/{id}/days`, `GET /runs/{id}/folds`, `GET /runs/{id}/days/{date}/trades` — one thing each
- [x] 2.4 `POST /compare` — aligned equity + headline metrics for N run ids (read-only)
- [x] 2.5 API tests (FastAPI TestClient) for list/filter/sort, detail, equity, folds, compare

## 3. Management UI (P3) — MVP visualization

- [x] 3.1 TanStack Query hooks for the read API in `frontend/src/`
- [x] 3.2 Expand `frontend/src/routes/backtest.tsx` — runs table: sortable/filterable (PF, Sharpe, maxDD, net), kind + PASS/REVIEW + promotion badges
- [x] 3.3 Run-detail view — equity + drawdown charts (existing chart theme), per-day P&L, metric cards, config viewer
- [x] 3.4 Walk-forward view — per-fold IS-vs-OOS table + stitched-OOS equity + verdict badge
- [x] 3.5 Day drill-down — every-minute status trace + trades + legs
- [x] 3.6 Compare view — overlay N runs' equity curves
- [x] 3.7 Playwright e2e specs for the new routes/components in `frontend/e2e/`; `npx playwright test` green (non-negotiable #10)

## 4. Launch + optimize (P4)

- [x] 4.1 `POST /runs`, `POST /sweeps`, `POST /walkforwards` — submit one async job each via `src/pdp/jobs/`, return job id; results persist to the warehouse on completion
- [x] 4.2 UI optimize panel — launch sweep/walk-forward (window, objective, grid); live progress over the jobs WebSocket
- [x] 4.3 OOS leaderboard — rank configs by a chosen metric
- [ ] 4.4 e2e: launch a tiny walk-forward from the UI and assert it lands in the runs table

## 5. Promotion workflow (P5)

- [x] 5.1 Create `src/pdp/strategy/promotion.py` — PASS-gate check + generate paper-first `strategies/<id>.yaml` from a run config + write `backtest_promotions` doc + flip `promotion_state`
- [x] 5.2 `POST /runs/{id}/promote` — reject non-PASS; on success run the promotion and return the written strategy id
- [x] 5.3 UI promote action — PASS-gated button with confirmation; show promotion history; reflect promotion badge in the runs table
- [x] 5.4 Tests: promotion rejected for REVIEW; accepted for PASS writes YAML + promotion doc; e2e for the promote flow

## 6. Validation & archive

- [x] 6.1 `task test` + `task lint` + `task typecheck` green; `cd frontend && npx playwright test` green
- [ ] 6.2 `openspec validate backtest-warehouse-ui --strict` passes
- [ ] 6.3 Update affected `CLAUDE.md` indexes (`src/pdp/backtest`, `src/pdp/mongo`, `frontend`, `scripts`, root) for the new files/collections/routes
- [ ] 6.4 Archive the change: `openspec archive backtest-warehouse-ui`
