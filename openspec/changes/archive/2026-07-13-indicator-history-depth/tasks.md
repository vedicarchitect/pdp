# Tasks — indicator-history-depth

> **Prerequisite:** `bar-session-anchoring` must be applied and `market_bars` rebuilt first.
> Backfilling depth into mis-anchored buckets deepens the error. Verify with:
> `git log --oneline -1 -- backend/pdp/market/bars.py` and confirm `_session_open_utc` exists.

## 1. Tests first (they fail on today's code)
- [x] 1.1 `tests/indicators/test_ema.py`: an `EMATracker` configured for period 200 that has consumed
      150 bars → `state.values` has no key `200`; after 200 bars → key present. **Finding:** this
      already passed on today's code with the realistic multi-period config
      (`[9,20,50,100,200]`) — `EMATracker` already omitted unconverged periods correctly (see
      group 4). Written and kept as a regression guard, not a red-to-green test.
- [x] 1.2 `tests/indicators/test_warmup.py`: required bars for `max(period)=200` is 1000
      (`5 × 200`); for `max(period)=14` it is 200 (the floor) — `TestRequiredBars`
- [x] 1.3 Warmup on an unknown timeframe (`"7m"`) raises, naming the timeframe — `TestLookbackDays`
- [x] 1.4 Warmup that finds 150 of 1000 bars emits exactly one `indicator_warmup_short` carrying
      `bars_found=150, bars_needed=1000`
- [x] 1.5 `tests/strategies/test_config_parity.py` — **scope changed, see README "Findings":**
      `StrangleConfig`/`backend/backtest/configs/strangle_*_hedged.yaml` has no `ema`/
      `suite_indicators` field to compare against; there is no live-vs-backtest period list to
      diff. Test instead guards that each live watchlist's `ema` periods are a superset of the
      bias engine's fixed 9/20/50 requirement, and that EMA(200) is configured for every
      underlying.

## 2. Configs — add period 200
- [x] 2.1 `backend/strategies/directional_strangle_nifty.yaml:20` → `periods: [9, 20, 50, 100, 200]`
- [x] 2.2 Same for `directional_strangle_banknifty.yaml` and `directional_strangle_sensex.yaml`
- [x] 2.3 **N/A — see README "Findings".** `backend/backtest/configs/strangle_*_hedged.yaml` has no
      `ema` field; nothing to add there.
- [x] 2.4 Confirmed via grep: only the three live configs and the promotion-workflow YAML template
      (`pdp/strategy/promotion.py`, generates future live configs) declared `family: ema`; the
      template was stale at `[9,20,50]` and updated to match.

## 3. Derive the warmup window
- [x] 3.1 `backend/pdp/indicators/warmup.py`: added
      `required_bars(indicators: list[dict[str, Any]]) -> int = max(200, 5 * max_period)`, scanning
      every period-like key (`periods`, `period`, `ma_period`, `fast`, `slow`, `signal`, ...) across
      registry-merged family params
- [x] 3.2 Added `lookback_days(timeframe, bars_needed) -> int` using `_TF_SESSION_BARS` plus a
      weekend/holiday pad (`× 7 / 5`, single ceiling — two-stage rounding broke exact-doubling on
      a config period change, see task 1.2's `TestLookbackDays`)
- [x] 3.3 Deleted `_TF_WARMUP_CALENDAR_DAYS` and `_DEFAULT_WARMUP_CALENDAR_DAYS`; fixed both call
      sites (`warm_up_indicator_engine`'s per-entry loop, `_warm_one`'s target_bars)
- [x] 3.4 Unknown timeframe raises `ValueError(timeframe)`, caught at the per-entry loop boundary
      and logged as `indicator_warmup_failed` (warmup still never blocks startup)
- [x] 3.5 Updated `test_warmup_mongo_query_uses_prior_session_start` and
      `test_warmup_full_mongo_skips_dhan_fallback`, which referenced the deleted constants
- [x] Also wired real `indicators:` config through to warmup: `pdp/runtime/groups.py`'s
      `_watchlist_dicts` and `warmup.configure_matrix_suites`'s entries previously dropped the
      `indicators` key, so `required_bars` would have silently floored to 200 for every real
      watchlist entry in production. Not explicitly listed as a subtask but required for 3.1-3.2
      to do anything outside tests.

## 4. Converged-only reporting
- [x] 4.1 **No code change needed** — audited `ema.py`: `EMATracker.update()` already filters
      `values` to `{p: v for p, v in self._values.items() if v is not None}`, and a period's value
      stays `None` until `n == p` bars have been seen. This was already correct.
- [x] 4.2 Audited `rsi.py`, `macd.py`, `vwma.py`, `period_levels.py` — all already gated correctly
      (RSI's `ma` is `None` until `ma_period` seen; MACD/VWMA return `None` entirely until their
      full window is seeded; PeriodLevels' fields stay `None` until a period boundary completes).
      No premature-value bug found in any of them. The proposal's Cause 2 was warmup *depth*
      (too few bars fetched), not a tracker convergence bug — see README "Findings".
- [x] 4.3 `warmup.py` emits one `indicator_warmup_short` per `(sid, tf, family)` short of its own
      `required_bars([cfg])`

## 5. Backfill depth
- [x] 5.1 `backend/scripts/backfill_market_bars.py` created: for each `WAREHOUSE_UNDERLYINGS` ×
      each underlying's live-configured derivable TF, computes `required_bars` and counts existing
      `market_bars` docs
- [x] 5.2 Derives missing 15m/30m/1H from the stored 1m series by importing `rollup_bars` directly
      from `scripts/oneoff/rebuild_market_bars.py` (sys.path trick, since `scripts/` isn't a
      package) — one bucket-math implementation, not reimplemented
- [x] 5.3 Falls back to Dhan only where 1m coverage itself is thin, reusing
      `scripts/backfill_spot.py`'s `_fetch_chunk`/`_write_day`; logs `indicator_backfill_1m_gap_dhan_fallback`
      naming the affected days
- [x] 5.4 Exits non-zero (`indicator_backfill_shortfall`) naming `(sid, tf, found, needed)` for any
      gap that remains after backfill
- [x] 5.5 Run for real 2026-07-12 — see README "Findings" for full per-`(sid, tf)` counts. NIFTY
      30m/1H went from 875/478 to 19,903/10,658 (needed 1000); BANKNIFTY/SENSEX not backfilled —
      not in this environment's `WAREHOUSE_UNDERLYINGS`, correctly out of this task's scope.

## 6. Startup depth summary
- [x] 6.1 `IndicatorEngine.seeding_summary(sid, tf) -> dict[(family, period|None), bool]` — `ema`
      reports per-period, every other suite family reports one `(family, None)` entry
- [x] 6.2 `pdp/runtime/groups.py` logs one `indicator_seeding_summary` line per strategy naming
      unseeded combinations, right after the warmup call
- [x] 6.3 `TestSeedingSummary` — partial and full seeding cases

## 7. Measure the cost
- [x] 7.1 Real warmup timing (all 3 live strategies × 5 TFs, against production Mongo, post-backfill
      depth): **5.19s total**. See README "Findings".
- [x] 7.2 Not warranted at this cost — no synchronous/background split added; 5.19s is well within
      any startup budget and runs once, off the tick hot path
- [x] 7.3 Confirmed structurally: warmup only calls `IndicatorEngine.seed_from_bars`, never
      `TickRouter.run` — no hot-path code was touched by this change

## 8. Verify against Kite
- [ ] 8.1 **Not done — no Kite credentials in this environment**, same constraint documented in
      `bar-session-anchoring` task 5.3. Substituting a Dhan-native comparison (as that change did)
      wasn't repeated here since it wouldn't newly validate anything task 5 already didn't cover
      via the exact-OHLC-parity rebuild.
- [ ] 8.2 Not done — depends on 8.1

## 9. Docs + validation
- [x] 9.1 Deleted the wrong "EMA200 = `--` → increase `_TF_WARMUP_CALENDAR_DAYS`" row from root
      `CLAUDE.md`; replaced with the two-cause (not-configured vs not-yet-converged) diagnosis
- [x] 9.2 `backend/pdp/indicators/CLAUDE.md`: documented `required_bars`/`lookback_days`, the
      convergence rule (already-true-before-this-change), what `--` means now, and the
      `StrangleConfig` no-`suite_indicators` caveat
- [x] 9.3 Combined re-baseline run 2026-07-13 (after `bias-input-completeness` landed, per
      `EXECUTION-ORDER.md`). See README "Combined re-baseline results (2026-07-13)" — verdict:
      supersede.
- [x] 9.4 `task test` green: **1064 passed, 2 intentional xfailed** (2026-07-12); ruff clean on
      every file this change touched (pre-existing baseline noise in `directional_strangle.py`
      [16 errors] and `pdp/strategy/promotion.py` [1 error] confirmed via `git stash` to predate
      this change); pyright on `warmup.py`+`bias.py` +7 errors over the 129 pre-existing baseline,
      all `reportUnnecessaryIsInstance`/`reportUnknownVariableType` in the same already-tolerated
      `dict[str, Any]`-config-typing style the file used before this change (not 0 errors — this
      module was never clean at strict pyright, unlike `bar-session-anchoring`'s `bars.py`)
- [x] 9.5 `openspec validate --strict indicator-history-depth` → "Change 'indicator-history-depth'
      is valid"

## Not yet done

Task group 8 (Kite indicator comparison) remains blocked — no Kite credentials in this
environment. Every other task, including 9.3 (combined re-baseline, 2026-07-13), is complete.
