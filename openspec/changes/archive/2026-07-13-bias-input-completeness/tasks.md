# Tasks — bias-input-completeness

> **Prerequisites:** `bar-session-anchoring` and `indicator-history-depth` applied. Wiring an input
> to mis-anchored or under-seeded bars trades one silent error for another.

## 1. Tests first (they fail on today's code)
- [x] 1.1 `tests/strategies/test_bias_inputs.py`: `_build_bias_inputs` requests pivots on `1D`, never
      on `5m` (assert with a spying `IndicatorReader`)
- [x] 1.2 With a `1w` pivot tracker configured, `cam_weekly` is non-null
- [x] 1.3 With `chain_hub.get_pcr("SENSEX")` stubbed to a float, `BiasInputs.pcr` is that float
- [x] 1.4 `tests/strategy/test_bias_satisfiability.py`: `w_cam_weekly>0` + no `1w` in watchlist →
      startup raises, message contains `w_cam_weekly` and `1w`
- [x] 1.5 `w_ema_1h>0` + `1H` entry without `ema` family → raises naming the family
- [x] 1.6 `w_pcr>0` + underlying not in the derived chain-poller underlyings → raises naming the
      underlying (see group 4 — this is no longer an `OPTIONS_UNDERLYINGS` setting)
- [x] 1.7 `w_cam_weekly=0.0` + no `1w` → startup succeeds
- [x] 1.8 All three shipped configs pass the satisfiability check after task 3 lands
      (`test_all_shipped_configs_are_satisfiable`)
- [x] 1.9 `tests/signals/test_bias.py`: a null input is recorded as `abstain` in the emitted breakdown
- [x] Also added (found during investigation, not in the original task list):
      `tests/indicators/test_warmup.py::test_weekly_pivot_seeds_from_single_prior_week_not_aggregate`
      — guards a real bug found in `_warm_one`'s prior-period HLC derivation (see group 3 findings)

## 2. Fix the two mis-wired reads
- [x] 2.1 `directional_strangle.py`: `pivot = ind.pivots(self.sid, "1D")` (was `"5m"`)
- [x] 2.2 `period_levels` reads `"5m"` — **verified correct, no change.**
      `PeriodLevelsTracker` accumulates day/week/month high-low from whatever bars it's fed and
      freezes at the boundary; the day's high fed via 5m bars equals the day's high fed via 1D
      bars (same underlying data, finer granularity). Confirmed by direct code read of
      `period_levels.py`'s `update()` — no per-timeframe assumption in the freeze logic.
- [x] 2.3 Deleted the stale comment claiming the `1w` snapshot is "seeded by 1w BarAggregator"

## 3. Configs — add the `1w` watchlist entry
- [x] 3.1 `backend/strategies/directional_strangle_{nifty,banknifty,sensex}.yaml`: added a
      **second** watchlist entry per underlying — `timeframes: [1w]`,
      `indicators: [{family: pivots}]` only. **Not the same entry as the main one** — see
      README "Findings": `WatchlistEntry.indicators` applies to every timeframe in that entry,
      so adding `1w` to the main entry would put EMA(200)/supertrend/psar/vwap on weekly bars
      too (needs ~19yr to converge) and disarm the strategy at every startup via
      `StrategyHost.start()`'s 200-bar warm check.
- [x] 3.2 **N/A — see README "Findings".** `backend/backtest/configs/strangle_*_hedged.yaml`
      (`StrangleConfig`) has no watchlist/indicators concept at all (confirmed in
      `indicator-history-depth`). Its `cam_weekly`/`cam_daily` come from
      `pdp/backtest/strangle_loader.py`, which computes Camarilla directly from resampled 1m
      spot bars (`_camarilla(_hlc(...))`) — already correct, already reads the true prior
      week/day HLC, nothing to add here.
- [x] 3.3 Confirmed via test + real bug fix (see README "Findings" for the full writeup):
      `warm_up_indicator_engine` already synthesizes `1w` bars from `1D` bars in Mongo when no
      native weekly bars exist yet, so no separate backfill run was needed. Found and fixed two
      real bugs in the process:
      1. `_warm_one`'s prior-period HLC derivation used a day-boundary filter that never
         matches a Monday-anchored `1w` bar, silently falling back to aggregating up to 10
         prior weeks' high/low together instead of using the single most recent completed
         week's own HLC.
      2. `IndicatorEngine.seed_prior_session_pivots` mutated the `PivotTracker`'s internal
         state but never refreshed the cached `Snapshot` `get_pivots()`/`get_snapshot()` read
         from — the correction was silently invisible to every consumer, for **every**
         timeframe with pivots configured (not just `1w`), since the tracker was seeded.
      Also exempted `tf == "1w"` from `StrategyHost.start()`'s 200-bar disarm check (weekly
      pivots seed from one completed week, not a 200-bar convergence count — 200 weeks is ~4
      years, which BANKNIFTY/SENSEX don't have).

## 4. SENSEX chain + warehouse
- [x] 4.1-4.3 **Redesigned per explicit user direction (2026-07-12): "keep credentials and
      general settings only in .env, rest all config keep it separately based on strategy."**
      `OPTIONS_UNDERLYINGS` and `WAREHOUSE_UNDERLYINGS` are **removed** from `settings.py`
      entirely rather than having `SENSEX` added to them. New
      `pdp.strategy.registry.strategy_underlyings(strategies_dir)` derives the underlying set
      from every loaded strategy YAML's `params.underlying` — `OptionsChainPoller` and
      `WarehouseService` now take an explicit `underlyings: list[str]` constructor arg computed
      this way (`pdp/runtime/groups.py`, `pdp/warehouse/__main__.py`,
      `scripts/backfill_market_bars.py`). SENSEX's chain and warehouse come online because
      `directional_strangle_sensex.yaml` already declares `params.underlying: SENSEX` — no
      `.env` edit needed, no separate SENSEX-specific setting either. This eliminates the bug
      class (a strategy's underlying silently absent from a hand-maintained global list), not
      just this one instance of it. Spec delta: `specs/multi-index-warehouse/spec.md`.
- [x] 4.2 (superseded) — no `.env` edit needed under the redesigned approach.
- [x] 4.4/4.5 **Not verified live** — no valid Dhan credentials in this environment
      (`DHAN_ACCESS_TOKEN` expired, per `indicator-history-depth`'s finding); confirmed via code
      read that `OptionsChainPoller.start()` logs `options_poller_started` with the
      `underlyings` list, so this is checkable the moment credentials are live.

## 5. Startup satisfiability check
- [x] 5.1 `pdp/signals/bias.py`: `_TF_FAMILY_REQUIREMENTS` map next to `BiasWeights` +
      `check_bias_satisfiability(weights, watchlist, *, underlying, options_underlyings)` +
      `BiasInputUnsatisfiable` exception. `w_swing` (any TF with `period_levels`), `w_orb` (just
      needs `15m` present, not a suite family — ORB is derived from the raw bar) and `w_pcr`
      (underlying membership in the derived chain-poller set) handled directly in the function
      body rather than forced into the `(tf, family)` map shape.
- [x] 5.2 `pdp/strategy/host.py`: `StrategyHost._check_bias_satisfiability(cfg, instance)`,
      called from `start()` right after the strategy instance is constructed. Gated on
      `isinstance(instance, DirectionalStrangle)` — not a generic `w_*` param sniff — so a
      strategy with an unrelated `w_*` param is never misidentified as bias-driven.
      `pdp.strategies.directional_strangle.weights_from_params(params)` (renamed from
      `_weights_from_params` — pyright flagged the private-name cross-module import) is shared
      by both `on_init` and this check so they read identical defaults.
- [x] 5.3 Verified: the raise is not caught anywhere in `start()` or its caller chain; it
      propagates out and would abort the `required=True` strategy-host group's startup exactly
      like any other unhandled exception in that path (same mechanism `broker-sync-visibility`
      established for `required=True` groups).
- [x] 5.4 `log.info("bias_inputs_satisfied", strategy_id=cfg.id, inputs=satisfied)` on success.

## 6. Vote breakdown logging
- [x] 6.1 `pdp/signals/bias.py`: added `VoteBreakdown` dataclass (`vote`, `weight`, `abstained`)
      and `BiasResult.breakdown: dict[str, VoteBreakdown]`, populated for all eight inputs
      (present or abstaining) in `score_bias`.
- [x] 6.2 `directional_strangle.py`: `bias_evaluated` event now also carries `breakdown`
      alongside the existing `votes`/`bucket`/`score`.
- [x] 6.3 Flattened to plain dicts (`{name: {"vote":..., "weight":..., "abstained":...}}`) before
      emission — JSON-serializable, queryable field names in OpenSearch
      (`breakdown.cam_weekly.abstained`), not a formatted string or a dataclass instance.

## 7. Re-baseline
- [x] 7.1-7.3 Combined re-baseline run 2026-07-13, after this change (per `EXECUTION-ORDER.md`).
      See README "Combined re-baseline results (2026-07-13)" — verdict: supersede.

## 8. Docs + validation
- [x] 8.1 `backend/pdp/signals/CLAUDE.md` created: the eight inputs + prerequisites table, the
      satisfiability rule, the vote-breakdown shape, the "1w needs its own watchlist entry"
      gotcha, and the "which underlyings get a chain poller" derivation.
- [x] 8.2 `docs/RUNBOOK.md` §19.4 rewritten: PCR/cam_daily/cam_weekly sections corrected (were
      stale — said PCR needs `LIVE=1`, said `cam_weekly` needs bar-aggregator work "not yet
      added"; both wrong even before this change per group 2/3's findings). Documents the
      derived-underlyings mechanism and the satisfiability check.
- [x] 8.3 `task test`: **1080 passed, 2 intentional xfailed** (2026-07-12, up from
      `indicator-history-depth`'s 1064 — 16 net new tests); ruff clean on every file this change
      touched (pre-existing baseline noise in `directional_strangle.py`, `host.py`,
      `pivots.py`, `groups.py`, `warehouse/__main__.py`, `test_warmup.py` confirmed unchanged
      by direct line-content comparison, not just count); pyright clean on every genuinely new
      symbol (`weights_from_params`, `BiasInputUnsatisfiable`, `check_bias_satisfiability`,
      `strategy_underlyings`) — remaining pyright noise on touched files is pre-existing
      motor/pymongo stub-typing gaps unrelated to this change's edits.
- [x] 8.4 `openspec validate --strict bias-input-completeness` → "Change 'bias-input-completeness'
      is valid" (includes the new `specs/multi-index-warehouse/spec.md` delta for the
      settings-to-strategy-config migration in group 4).

## Status (2026-07-13)

All task groups (1–8) complete, including group 7 (combined re-baseline). See README "Combined
re-baseline results (2026-07-13)" for the full NIFTY/BANKNIFTY/SENSEX numbers and the supersede
verdict. Ready to archive.
