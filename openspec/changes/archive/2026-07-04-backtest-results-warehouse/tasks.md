## 1. Foundations (collections + thresholds)

- [x] 1.1 Add `backtest_sweeps` and `backtest_decisions` collections + indexes in `pdp/mongo/collections.py` (`_ensure_backtest_*`, `init_collections`).
- [x] 1.2 Centralize the four verdict thresholds (net>0, PF>1.2, Sharpe>0.5, ≥60% positive OOS folds) as the single source in `pdp/backtest/store.py`; make `backtest/strangle_walkforward.py` import them instead of inline literals.
- [x] 1.3 Add doc builders + idempotent upserts to `pdp/backtest/store.py`: `build_sweep_doc`/`upsert_sweep` and `build_decision_docs`/`upsert_decisions`.

## 2. Real sweeps + leaderboard

- [x] 2.1 Implement grid expansion + per-combination execution in `backtest_sweep_handler` (`pdp/backtest/job_handlers.py`), reusing `backtest/run.py` grid logic (`parse_st`/`parse_param_sweep`/`apply_overrides`/`aggregate`) and the batch-loader window pattern from `backtest/sweep_all.py`; reject empty grids.
- [x] 2.2 Rank combos by objective `(-pf, -net)` and persist to `backtest_sweeps` with `best_param`.
- [x] 2.3 Add `GET /api/v1/strangle-backtests/sweeps/{sweep_id}` (leaderboard) to `warehouse_routes.py`.
- [x] 2.4 Add `sweep_id`/`param_grid` to the `backtest-runs` OpenSearch mapping (`pdp/observability/mappings.py`) and populate on sweep-combo run docs.

## 3. Decision trace (why entry / why exit)

- [x] 3.1 Emit strategy-agnostic decision events from `pdp/backtest/strangle_sim.py` at the points it already computes reasons (ST flip, entry, scale-in, rollup on premium decay, exit tp/stop/flip/squareoff, reentry cooloff) — map internal reasons onto the closed reason-code vocabulary.
- [x] 3.2 Persist events (default) to `backtest_decisions` via `store.py`; per-day summary stays in `backtest_days`. Do not store per-minute snapshots by default (incl. sweep combos).
- [x] 3.3 Add a `backtest-decisions` OpenSearch family + mapper in `pdp/observability/{mappings,sinks}.py`; dual-sink events.
- [x] 3.4 Add on-demand full per-minute trace: a replay path that materializes one run+date's every-minute snapshot (pin config/window from the run doc for deterministic replay).
- [x] 3.5 Add `GET /api/v1/strangle-backtests/runs/{id}/decisions?date=&full=` to `warehouse_routes.py`.

## 4. Promotion rationale

- [x] 4.1 Extend `pdp/strategy/promotion.py` + the promote route in `warehouse_routes.py` to snapshot the evidence onto `backtest_promotions`: stitched-OOS metrics, per-threshold PASS-vs-actual breakdown, positive-fold fraction, source-run link, and an optional operator `note`.
- [x] 4.2 Emit a discrete promotion event to OpenSearch (new sink/event).
- [x] 4.3 Add `GET /api/v1/strangle-backtests/runs/{id}/promotion` returning the rationale.

## 5. DB-first cutover (no local files)

- [x] 5.1 Make run/walk-forward entry points persist to Mongo by default (not opt-in) and route logs to OpenSearch via the existing indexer.
- [x] 5.2 Deprecate `pdp/backtest/strangle_report.py:RunWriter` local archival and the `logs/*.log` / `wf.csv` outputs, behind a short-lived settings fallback flag.
- [x] 5.3 Confirm a fresh run writes no local result files (results in Mongo, logs in OpenSearch).

## 6. Ingest existing track record + retention

- [x] 6.1 Bulk-ingest the ~33 local `backtest/runs/*` folders via `scripts/ingest_backtest_run.py` / `BacktestStore.ingest_run_folder` (incl. the ₹1.15 Cr NIFTY + ₹35L BANKNIFTY runs).
- [x] 6.2 Add ingest→verify→remove retention: remove a local run folder only after its data is confirmed present in Mongo; never remove unverified.

## 7. Skills

- [x] 7.1 `.claude/skills/backtest-run/SKILL.md` (`/backtest:run`) — launch a single backtest, summarize metrics + verdict.
- [x] 7.2 `.claude/skills/backtest-sweep/SKILL.md` (`/backtest:sweep`) — launch a sweep, summarize leaderboard + `best_param`.
- [x] 7.3 `.claude/skills/backtest-promote/SKILL.md` (`/backtest:promote`) — review rationale evidence, capture note, promote a PASS run; refuse non-PASS.
- [x] 7.4 `.claude/skills/backtest-ingest/SKILL.md` (`/backtest:ingest`) — ingest local runs, verify, then remove (guarded).
- [x] 7.5 `.claude/skills/backtest-explain/SKILL.md` (`/backtest:explain`) — reconstruct the why-entry/why-exit narrative for a run+date from `backtest_decisions`.

## 8. Tests + spec sync

- [x] 8.1 Unit tests: sweep grid expansion + leaderboard persistence/ranking; decision-event emission + reason codes; promotion evidence snapshot; ingest-then-remove retention guard.
- [x] 8.2 `task test` / `task lint` / `task typecheck` clean for touched modules; `openspec validate backtest-results-warehouse --strict` passes.
- [x] 8.3 Run `task search:up && task search:init`; confirm `backtest-decisions` index + `sweep_id` fields + promotion events appear.
