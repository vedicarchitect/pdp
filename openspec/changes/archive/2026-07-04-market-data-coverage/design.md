## Context

Coverage today is implicit: `gap_backfill.days_missing()` computes missing option-days on demand,
`audit_options_coverage.py` prints a NIFTY-only report, and `market_bars`/`option_bars` hold the
raw data. There is no coverage collection or API. The self-heal loop
(`warehouse/service.py:_run_gap_backfill`) skips BANKNIFTY/SENSEX with a "not implemented" warning
even though the CLI and `backfill_gaps()` core are already multi-index. Backtest inputs are assembled
by `strangle_loader.py` from spot (→ EMAs/VWAP/ORB), prior-week spot + `index_levels` (→ weekly
Camarilla), VIX, and option OI (→ PCR). `completeness.py` gates only the spot 1m series.

## Goals / Non-Goals

**Goals:**
- One coverage API across NIFTY/BANKNIFTY/SENSEX and all input families.
- A gap radar that flags missing input families per (index, date) in backtest-input terms.
- One-click delta-fill for any index/family via the existing job system.
- Background self-heal for all three indices.
- Coverage snapshots + dashboard in OpenSearch.

**Non-Goals:**
- The Flutter coverage UI (change 5 renders it; this change ships the API + radar + dashboard).
- New market-data *sources* — futures ingestion is out of scope; the radar reports futures presence
  and exposes a backfill hook only if a source exists.

## Decisions

### 1. Coverage is computed, not a new stored index (except OpenSearch snapshots)
`GET /api/v1/coverage` runs the aggregations live: `option_bars` has a top-level `underlying` so
min/max + `days_missing` work directly; `market_bars` (spot/VIX) is keyed by Dhan SID (NIFTY 13,
BANKNIFTY 25, SENSEX 51, VIX 21) so spot coverage maps via SID; `index_levels` gives Camarilla
coverage. Rationale: no new source-of-truth collection to keep in sync; the DB *is* the truth.
OpenSearch receives periodic snapshots for trend/history only.

### 2. Gap radar promotes `completeness.py` to per-family
Add per-family readiness functions reusing existing helpers: spot gate (existing
`spot_completeness`), options (`days_missing`), VIX (spot-style count on sid 21), weekly Camarilla
(prior-week spot present OR `index_levels` present), futures (presence check / follow-up). Each
(index, date) yields a family→status map with human labels the UI can render. Rationale: the radar
speaks the backtest's input language ("VWAP missing" = spot gap) rather than raw collection names.

### 3. Delta-fill reuses housekeeping jobs; plumb `symbol`
`pdp/housekeeping/tasks.py` `backfill_spot`/`backfill_options` gain a `symbol` arg passed to the CLI
(`--symbol`), plus new `backfill_levels`/`backfill_vix` handlers. `_VALID_TASKS` +
`housekeeping/routes.py` gain the new task names. Delta semantics = `--to today --only-missing`.
Rationale: the async job system already streams progress over `/ws/jobs`; only the wiring is missing.

### 4. Multi-index self-heal: remove the skip
`_run_gap_backfill` loops `WAREHOUSE_UNDERLYINGS`, loading each underlying's expiry calendar from its
`*_EXPIRY_CACHE_PATH` and calling `run_gap_backfill(..., underlying=...)`. Skip only when the expiry
cache is missing (clear warning). Rationale: the core is already parameterized; this deletes the
NIFTY-only guard the spec's escape clause allowed.

### 5. OpenSearch additive
Add a `data-coverage` family + mapper (`observability/{mappings,sinks}.py`) and an
`NN_data_coverage.ndjson` dashboard (index-pattern `pdp-data-coverage-*` + gap/coverage % visuals).
Picked up by `ensure_templates()` / `task search:init`.

## Risks / Trade-offs

- [Live aggregation cost on large collections] → `option_bars` holds tens of millions of rows with
  no `(underlying, ts)`-only index, so an unbounded sort-by-ts query for min/max is a full scan
  (this hung the endpoint in testing before the fix). Resolved by deriving min/max from the
  present-day set the window-bounded aggregation already computes, rather than a separate
  full-collection sorted query or a caching layer — every coverage aggregation, including min/max,
  stays bounded to `[window_from, window_to]`. Trade-off: reported min/max is the earliest/latest
  *within the requested window*, not the true all-time first/last date; callers needing all-time
  bounds should widen the window rather than expect a separate unbounded lookup.
- [Spot coverage lacks an `underlying` name field] → map by SID (13/25/51/21); centralize the SID map
  next to `UNDERLYING_REGISTRY`.
- [Futures family has no source yet] → report as "missing/unavailable" and gate its backfill action;
  a real futures source is a follow-up, not a blocker for the radar.
- [Self-heal now hits BANKNIFTY/SENSEX Dhan endpoints] → same off-event-loop worker thread as NIFTY;
  respects `WAREHOUSE_GAP_BACKFILL_ENABLED` and the interval.

## Migration Plan

1. Add `symbol` plumbing + new backfill tasks to housekeeping (backward compatible, NIFTY default).
2. Add the coverage module + `GET /api/v1/coverage` + gap-radar functions (reuse existing helpers).
3. Remove the non-NIFTY skip in `_run_gap_backfill`; verify BANKNIFTY/SENSEX heal.
4. Add the `data-coverage` OpenSearch family + dashboard; emit periodic snapshots.
5. Author `/data:coverage` + `/data:gapfill` skills.
Rollback: coverage API + radar are read-only additions; the self-heal change is guarded by
`WAREHOUSE_GAP_BACKFILL_ENABLED` and the expiry-cache presence check.

## Open Questions

- Should the coverage snapshot to OpenSearch be emitted by the self-heal loop (natural cadence) or by
  a dedicated periodic task? Leaning the self-heal loop since it already scans coverage each cycle.
