# backtest-console-readability-and-nav

## Why

The backtest console is the tool that decides which config gets promoted to paper — but today
it is broken and unreadable, and the app has duplicate navigation. All verified against source:

1. **Coverage tab times out (8s DioException).** `GET /api/v1/coverage`
   (`warehouse/routes.py` → `all_coverage`, `coverage.py:291-305`) runs the per-underlying
   probes **serially** (`results[name] = await underlying_coverage(...)` in a loop), and each
   `underlying_coverage` (`:242-289`) runs **five family probes serially** (`_spot_gaps`,
   `_options_family`, VIX via `_spot_gaps`, daily + weekly `_levels_family`, plus
   `per_expiry_coverage`). The options probe (`gap_backfill.days_missing:358-385`) does a
   `$group` over the tens-of-millions-row `option_bars` on a `(underlying, timeframe, ts)`
   match, and `_options_family`/`_spot_gaps` each open a **fresh `MongoClient`**
   (`coverage.py:133-135`). VIX is recomputed once per index. → 3 × ~6 serial Mongo round-trips
   → exceeds the 8s Dio timeout.

2. **Verdict + Promotion are `--` for every run.** `verdict` is only computed for
   **walk-forward** runs (`store.py:282-301`, gated on a folds CSV); single runs pass
   `verdict=None` to `build_run_doc` (`store.py:156`) and sweep combos hard-code `None`
   (`store.py:592`). `promotion_state` starts `"none"` (`store.py:155`) and only flips via the
   PASS-gated promote endpoint. Single runs dominate, so both columns are structurally always
   `--`.

3. **Sweeps/walk-forward are jargon, not "which param won".** The data exists — sweeps rank
   combos by `(-pf, -net)` and store `best_param` (`store.py:406,426`); walk-forward stores a
   winning `pick_label` per fold + a PASS/REVIEW verdict (`store.py:254,282`). But the API
   returns raw combo/fold docs and nothing renders "config X won, here's why" in plain English.

4. **Nothing is grouped by index.** The index lives only inside `config.underlying`
   (`store.py:133`), not a top-level field; `GET /runs` filters on `kind`/`strategy_id`/
   `verdict` only — there is **no `underlying` filter** (`warehouse_routes.py:90-108`). Coverage
   is per-underlying but runs/sweeps are not, violating the program's group-by-index principle.

5. **Duplicate navigation.** The "More → Management Hub" screen
   (`manage/presentation/manage_hub_screen.dart:22-36`) repeats **Execution** and **Journal**
   tabs that already have their own primary home in the left nav — two entry points to the same
   screens.

## What Changes

- **Fast coverage (< 2s).** Parallelize the per-underlying and per-family probes with
  `asyncio.gather` instead of serial awaits; compute VIX **once** and reuse it across indices;
  use a **pooled/shared Mongo client** instead of a fresh `MongoClient` per probe; add or lean
  on a covering index for the options `(underlying, timeframe, ts)` `$group` (or bound the
  window). Raise the Flutter `receiveTimeout` as a backstop only, not the primary fix.
- **Grade every run.** Compute a verdict for **single** runs (and sweep best-combos) using the
  same thresholds walk-forward already uses (`WF_PASS_NET/PF/SHARPE/POS_FRAC`, `store.py:26-29`)
  via a shared `verdict_breakdown`, so the Verdict column shows PASS/REVIEW instead of `--`.
  `promotion_state` still only flips through the existing PASS-gated promote flow.
- **Plain-English "which param won", per index.** Add a leaderboard-by-index endpoint/view that
  names the best config per index from `best_param` + walk-forward `pick_label` as a readable
  card — "NIFTY: best = ST(10,2)/15m, PF 5.72, PASS, promoted" — not raw combo JSON. Add layman
  copy to the Sweeps + folds views explaining what a sweep is and what walk-forward PASS proves.
- **Group by index everywhere.** Promote `underlying` to a **top-level field** on
  `backtest_runs` / `backtest_sweeps` (backfill from `config.underlying`), add an `underlying`
  query filter to `GET /runs`, and default the Flutter Runs / Sweeps / Coverage tabs to a
  per-index grouped layout (the index selector already exists).
- **Remove duplicate nav.** Drop the **Execution** and **Journal** tabs from the Management Hub
  screen (they stay in the left nav as their primary home); keep Strategies / Housekeeping /
  Jobs-Audit in the Hub.

## Impact

- **Modified specs:** `market-data-coverage` (coverage API is parallel + pooled, returns < 2s),
  `backtest-warehouse` (single-run verdict; top-level `underlying` + filter; per-index
  leaderboard), `flutter-backtest-console` (per-index grouped runs/sweeps/coverage; graded
  runs; layman sweep/WF explainer; no coverage timeout), `trading-app` (app shell nav has no
  duplicate Execution/Journal entry points).
- **Affected backend code:** `pdp/warehouse/coverage.py` (`asyncio.gather`, pooled client,
  compute-VIX-once), `pdp/warehouse/routes.py`, `pdp/mongo/collections.py` (covering index),
  `pdp/backtest/store.py` (single-run verdict via `verdict_breakdown`; top-level `underlying`
  on `build_run_doc` + sweep docs), `pdp/backtest/warehouse_routes.py` (`underlying` filter on
  `/runs`; a per-index leaderboard resource), a one-off backfill of `underlying` onto existing
  run/sweep docs.
- **Affected Flutter code:** `app/lib/features/backtest/**` (per-index grouped runs/sweeps/
  coverage tabs, verdict chips, plain-English leaderboard cards + sweep/WF explainer copy,
  higher `receiveTimeout` backstop), `app/lib/features/manage/presentation/manage_hub_screen.dart`
  (drop Execution + Journal tabs).
- **Reuses (does not reinvent):** the existing `verdict_breakdown` + `WF_PASS_*` thresholds,
  `best_param` / `pick_label`, `days_missing` / `expected_contracts` / `trading_days` gap
  helpers, the existing index selector and jobs WebSocket in the console.
- **Out of scope:** any new backtest metric or strategy; the `futures` coverage family (already
  removed in Change C); the live-P&L/ledger work (Change B). The Management Hub's Strategies /
  Housekeeping / Jobs-Audit tabs are unchanged.
- **Prerequisite:** Changes A, B, C archived first (strict A→B→C→D sequencing). In particular
  the coverage family set is already `spot/options/vix/levels_weekly` (no `futures`) after
  Change C.
