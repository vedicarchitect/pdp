## Context

The backtest warehouse (`pdp/backtest/store.py`, `warehouse_routes.py`, `mongo/collections.py`)
already persists `backtest_runs`/`backtest_days`/`backtest_folds`/`backtest_trades` and dual-sinks
runs to OpenSearch (`store.py:_ship_backtest`, families in `observability/{mappings,sinks}.py`). Gaps
this change closes (confirmed by exploration):

- `backtest_sweep_handler` (`job_handlers.py:87`) ignores the grid and runs a single config — sweeps
  are a no-op. Real grid + ranking logic exists but only in the CLI (`backtest/run.py`:
  `parse_st`/`parse_param_sweep`/`apply_overrides`/`aggregate`/`print_table` sorting by `(-pf,-net)`;
  `backtest/sweep_all.py`). Nothing is persisted.
- No leaderboard/`best_param` collection; `backtest_runs` is only query-sortable by metric.
- Promotion (`strategy/promotion.py` + `warehouse_routes.py:320`) records `{run_id, verdict, config,
  strategy_id, yaml_path, promoted_at}` — no justifying evidence.
- Verdict thresholds are duplicated: `store.py:22-26` constants and inline literals in
  `strangle_walkforward.py:339`.
- The rich every-minute `BarStatus` trace + per-fill notes + per-leg exit reasons are written to
  local files by `strangle_report.py:RunWriter` (status.log/trades.csv/legs.csv) and only coarsely
  into `backtest_days.status_log[]`. They are not a queryable, strategy-agnostic store.
- Results are filesystem-durable by spec today; the user's directive is DB-first, **no local files**,
  logs to OpenSearch.

## Goals / Non-Goals

**Goals:**
- Make async sweeps actually sweep, and persist a ranked leaderboard + `best_param`.
- Persist a strategy-agnostic decision-event trace (`backtest_decisions`) answering why-entry/why-exit;
  events by default, full per-minute trace on demand.
- Make promotion self-contained: auto evidence snapshot + optional operator note.
- Cut over to DB-first: new runs write to Mongo + OpenSearch only; deprecate local file archival.
- Ingest the ~33 existing local runs, then remove them once verified.
- Centralize verdict thresholds in one place.

**Non-Goals:**
- The Flutter UI (change 5), data-coverage/gap-radar (change 2), generic paper comparison (change 3),
  and the unified strategy registry (change 4). This change is the backend data spine only.
- Changing the strangle simulation logic or fill semantics — we only *emit* decision events from the
  reasoning the sim already computes.

## Decisions

### 1. Sweep execution reuses the CLI grid, not a new engine
`backtest_sweep_handler` will expand the grid and run each combination via the same code path the CLI
uses (`backtest/run.py` grid mode for ST-family; strangle sweeps via the grouped-knob approach), then
rank by objective `(-pf, -net)` as `print_table` already does. Rationale: the ranking/aggregation is
proven; duplicating it risks divergence. Alternative rejected: a fresh in-handler sweep loop.

### 2. New collections `backtest_sweeps` and `backtest_decisions`
- `backtest_sweeps`: `{ sweep_id, kind, window, grid, objective, combos: [{ rank, params, metrics }],
  best_param, created_at }`, keyed by `sweep_id`, upsert-idempotent. Doc builder + upsert added to
  `store.py`; collection + indexes in `mongo/collections.py`.
- `backtest_decisions`: one doc per decision event `{ run_id, strategy_id, ts_ist, date, event,
  reason, sub_reason?, action, snapshot: { score, bucket, votes, st, ema, vix, pcr, legs, pnl } }`,
  keyed by `(run_id, ts_ist, event)`. Reason codes: `st_flip | entry | scale_in | rollup | exit |
  reentry`; `rollup` carries `premium_decay`, `exit` carries `tp|stop|flip|squareoff`, `reentry`
  carries `cooloff_15m`. Schema is strategy-agnostic (snapshot is an open map) so non-strangle
  strategies emit the same shape. Rationale: keeps "why" queryable and generic; per-event (not
  per-minute) keeps volume bounded.

### 3. Events by default, full per-minute trace on demand
The sim already produces a per-minute `BarStatus`. By default we persist only bars where a decision
event fires (plus the per-day summary already in `backtest_days`). A full-trace request
(`?full=true` on the decision-trace endpoint, or a run-time flag) re-materializes the every-minute
snapshot for one run+date by replaying that day — we do **not** store every minute for every run or
sweep combo. Rationale: user asked for events by default, full detail only when asked; a full sweep
would otherwise write millions of docs.

### 4. Promotion evidence snapshot
Extend `promote_run` (`strategy/promotion.py`) + the promote route to copy the justifying evidence
onto the `backtest_promotions` doc at promote time: stitched-OOS metrics + per-threshold PASS-vs-actual
breakdown (net>0, PF>1.2, Sharpe>0.5, ≥60% positive OOS folds) + positive-fold fraction + source-run
link, plus an optional `note`. Emit a discrete promotion event to OpenSearch. The evidence is read
from the source run's `backtest_runs` doc (`stitched_oos`, `metrics`) so it is a point-in-time snapshot.

### 5. Centralize verdict thresholds
Move the four thresholds to a single module-level source (in `store.py`, already the place that
computes the stored verdict) and have `strangle_walkforward.py` import them instead of re-declaring
literals. Rationale: one source of truth; the promotion breakdown and the stored verdict must agree.

### 6. DB-first cutover
Deprecate `strangle_report.py:RunWriter` local archival and the `logs/*.log`/`wf.csv` outputs. Run
entry points persist to Mongo (now default, not opt-in) and route logs to OpenSearch via the existing
indexer. Legacy `backtest/runs/*` remain only as the ingest source. Rationale: matches the DB-first,
no-local-files directive; OpenSearch is already wired for logs.

### 7. OpenSearch additions are additive
Add `sweep_id`/`param_grid` to the `backtest-runs` mapping, a `backtest-decisions` family + mapper in
`observability/{mappings,sinks}.py`, and a promotion event. `ensure_templates()` picks new families
up at startup / `task search:init`; no settings changes.

## Risks / Trade-offs

- [Sweep volume — a large grid runs many backtests] → reuse the batch-loader window (load once, run
  per combo) as `sweep_all.py` does; persist combos to the leaderboard, not as individual
  `backtest_runs` unless single-run detail is explicitly requested.
- [DB-first removes the filesystem safety net] → ingestion is verified-before-remove; nothing is
  deleted until confirmed in Mongo. Logs still exist (in OpenSearch).
- [On-demand full trace requires deterministic replay] → the sim is deterministic for a fixed config
  + window + data; re-materializing a single day reproduces the same snapshot. Guard against data
  drift by pinning the run's config/window from the DB when replaying.
- [Decision-event schema churn across strategies] → keep `snapshot` an open map and the reason codes a
  small closed vocabulary; strategies map their internal reasons onto these codes.

## Migration Plan

1. Add collections + doc builders + threshold centralization (no behavior change yet).
2. Implement real sweep handler + leaderboard persistence.
3. Emit decision events from the strangle sim; wire `backtest_decisions` + OpenSearch family.
4. Extend promotion with evidence snapshot + note + promotion event.
5. Flip run entry points to DB-first; deprecate `RunWriter`/local logs (route to OpenSearch).
6. Ingest the ~33 existing local runs via `scripts/ingest_backtest_run.py`; verify; then remove folders.
Rollback: DB-first flip and RunWriter deprecation are the only breaking steps; keep them behind a
short-lived settings flag so a run can fall back to filesystem archival if the DB path regresses.

## Open Questions

- Should sweep combos that a user later wants to inspect at day/trade granularity be re-run on demand
  (consistent with the on-demand full-trace model), or should the top-K by objective auto-persist full
  `backtest_days`? Leaning re-run-on-demand for the top pick; confirm during tasks.
