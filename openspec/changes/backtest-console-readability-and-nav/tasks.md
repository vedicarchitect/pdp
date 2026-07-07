# Tasks — backtest-console-readability-and-nav

> Implementation contract. Every task states the exact file, symbol, and expected behaviour so
> any implementer produces the same result. Line numbers are as-of change authoring and may
> drift — always locate by symbol name. Prerequisite: Changes A, B, C archived (strict A→B→C→D).

## 1. Fast coverage (< 2s) — backend

- [ ] 1.1 In `pdp/warehouse/coverage.py::all_coverage` (`:291-305`), replace the serial
  per-underlying loop (`results[name] = await underlying_coverage(...)`) with
  `asyncio.gather(*[underlying_coverage(...) for name in underlyings])`, preserving the
  per-underlying keys in the response.
- [ ] 1.2 In `underlying_coverage` (`:242-289`), parallelize the five family probes with
  `asyncio.gather`: `_spot_gaps` (spot), `_options_family`, VIX (`_spot_gaps` on `SID_MAP["VIX"]`),
  `_levels_family` daily, `_levels_family` weekly, and `per_expiry_coverage`. They are
  independent reads — gather them rather than awaiting in sequence.
- [ ] 1.3 Compute VIX coverage **once** for the whole request, not once per underlying (VIX is
  index-independent). Hoist the VIX probe out of `underlying_coverage` into `all_coverage`,
  compute it a single time, and pass the result into each underlying's response assembly.
- [ ] 1.4 Use a **single shared/pooled Mongo client** for the whole coverage request instead of
  opening a fresh `MongoClient` per probe (`coverage.py:133-135` in `_options_family`/the
  thread helper). Pass the app's existing Motor/PyMongo handle (or one pooled client created
  once per request) into `days_missing` and the level/spot probes. Do not open a client inside
  a per-family helper.
- [ ] 1.5 Ensure the options `$group` (`gap_backfill.days_missing:373-379`, match on
  `(underlying, timeframe, ts)`) is index-supported: confirm/add a covering compound index
  `(underlying, timeframe, ts)` on `option_bars` in `pdp/mongo/collections.py` so the match+group
  does not collection-scan. If adding an index, make it idempotent (create-if-absent) in the
  existing index-ensure path.
- [ ] 1.6 Target: `GET /api/v1/coverage` returns in < 2s for a 90-day window across all three
  indices. Measure and record the before/after latency in the completion summary.
- [ ] 1.7 Backstop only: raise the Flutter `receiveTimeout` for the coverage call in the
  backtest data source so a slow cold cache does not throw — but 1.1–1.5 are the real fix, not
  the timeout bump.

## 2. Grade every run (verdict) — backend

- [ ] 2.1 In `pdp/backtest/store.py`, compute a verdict for **single** runs too. Reuse the
  existing thresholds `WF_PASS_NET/PF/SHARPE/POS_FRAC` (`:26-29`) and the `verdict_breakdown`
  helper (`:37-51`). For a single run, derive PASS/REVIEW from the run's own headline metrics
  (net > NET, PF > PF, Sharpe > SHARPE; positive-fraction is walk-forward-only, so for a single
  run use the applicable subset). Pass the computed verdict into `build_run_doc` instead of
  `None` (`:156`).
- [ ] 2.2 Compute a verdict for the sweep **best-combo** doc as well (currently hard-coded
  `None` at `:592`): grade the top-ranked combo by the same thresholds so a sweep's headline
  isn't `--`.
- [ ] 2.3 `promotion_state` remains `"none"` at creation (`:155`) and only flips through the
  existing PASS-gated `POST /runs/{id}/promote` flow — do NOT auto-promote. The Verdict column
  becomes PASS/REVIEW everywhere; the Promotion column stays accurate (promoted only when the
  user promotes a PASS run).
- [ ] 2.4 Add/adjust a unit test in `tests/backtest/` asserting a single run with metrics above
  the thresholds gets `verdict == "PASS"` and one below gets `"REVIEW"`, and that
  `promotion_state` is still `"none"` until promotion.

## 3. Top-level `underlying` + filter — backend

- [ ] 3.1 In `pdp/backtest/store.py::build_run_doc` (`:108-156`), add a top-level
  `underlying` field set from `config.get("underlying")` (alongside the existing nested
  `config.underlying`). Do the same for the sweep doc builder (`:~592`) and the walk-forward
  doc path.
- [ ] 3.2 One-off backfill: add a small idempotent migration/script that sets top-level
  `underlying` on all existing `backtest_runs` / `backtest_sweeps` docs from their
  `config.underlying`, so historical runs are groupable. Safe to re-run.
- [ ] 3.3 In `pdp/backtest/warehouse_routes.py::list_runs` (`:90-108`), add an `underlying`
  query param and include `filt["underlying"] = underlying.upper()` when present, mirroring the
  existing `kind`/`strategy_id`/`verdict` filters.
- [ ] 3.4 Add a per-index leaderboard resource, e.g. `GET /runs/leaderboard` (or
  `/leaderboard?underlying=`), returning, per index, the best config from `best_param` +
  walk-forward `pick_label` with its headline metrics, verdict, and promotion state — the data
  a plain-English card renders. Compute from existing docs; no new store.

## 4. Flutter — graded, grouped, plain-English console

- [ ] 4.1 In `app/lib/features/backtest/**`, render the Verdict column from the now-populated
  `verdict` field (PASS/REVIEW chip via theme tokens, never inline color); it must no longer
  show `--` for single runs.
- [ ] 4.2 Default the Runs, Sweeps, and Coverage tabs to a **per-index grouped** layout
  (NIFTY/BANKNIFTY/SENSEX section headers or the existing index selector driving a grouped
  view). Wire the `underlying` filter (task 3.3) into the Runs tab query.
- [ ] 4.3 Add a plain-English **leaderboard-by-index** card fed by the leaderboard resource
  (task 3.4): "NIFTY: best = ST(10,2)/15m, PF 5.72, PASS, promoted" — not raw combo JSON.
- [ ] 4.4 Add layman explainer copy to the Sweeps + folds views: what a sweep is ("we tried N
  parameter sets; this one had the best profit-factor"), what walk-forward proves ("optimized
  on past data, then tested on unseen data — PASS means it held up"), and a one-line verdict
  reason per run derived from `verdict_breakdown`.
- [ ] 4.5 Update the backtest domain models + data source (live + mock per `AppConfig.useMock`)
  for the new top-level `underlying`, populated `verdict`, and leaderboard shape.

## 5. Flutter — remove duplicate nav

- [ ] 5.1 In `app/lib/features/manage/presentation/manage_hub_screen.dart`, remove the
  **Execution** and **Journal** entries: drop the `Tab(icon: Icon(Icons.monitor_heart), text:
  'Execution')` (`:23`) and `Tab(icon: Icon(Icons.book), text: 'Journal')` (`:24`) from the
  `TabBar`, and the corresponding `StrategyExecutionTab()` (`:33`) and `JournalTab()` (`:34`)
  from the `TabBarView`. Keep Strategies, Housekeeping, Jobs / Audit.
- [ ] 5.2 Confirm the `TabController` length (if explicit) is updated to match the reduced tab
  count, and that Execution + Journal remain reachable via their left-nav destinations
  (`app_shell.dart`) — they are not being removed from the app, only from the Hub.
- [ ] 5.3 Remove any now-unused imports of `StrategyExecutionTab` / `JournalTab` in the hub
  screen (leave the tab widgets themselves in place — they are still used by the left-nav routes).

## 6. Verify

- [ ] 6.1 `task test` green for `tests/backtest/`, `tests/warehouse/`; `task lint` clean on all
  edited modules (pre-existing debt excluded). New verdict test from 2.4 passes.
- [ ] 6.2 `GET /api/v1/coverage` for a 90-day, 3-index window returns in < 2s (measure); every
  `GET /runs` doc carries a top-level `underlying` and a non-null `verdict`; `GET /runs?underlying=NIFTY`
  filters correctly; the leaderboard resource names a best config per index.
- [ ] 6.3 Flutter: Coverage tab loads without a DioException; Verdict shows PASS/REVIEW (no
  `--`); Runs/Sweeps/Coverage are grouped by index; a plain-English leaderboard card + sweep/WF
  explainer copy are present; the Management Hub no longer shows Execution or Journal tabs, and
  both are still reachable from the left nav.
- [ ] 6.4 `cd app && flutter analyze && flutter test` green.
- [ ] 6.5 `openspec validate backtest-console-readability-and-nav --strict`; archive on green.
