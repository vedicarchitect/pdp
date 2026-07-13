# indicator-history-depth — minimal context

Read only these to work this change. **Do not start until `bar-session-anchoring` is applied.**

| File | Why |
|------|-----|
| `backend/pdp/indicators/warmup.py` | `_TF_WARMUP_CALENDAR_DAYS:51-61` and `_DEFAULT_WARMUP_CALENDAR_DAYS:62` — deleted here; call sites at `:111`, `:148` |
| `backend/pdp/indicators/ema.py` | `EMATracker` computes only the periods it is given; must omit unconverged ones |
| `backend/pdp/indicators/engine.py` | Startup depth summary lands here |
| `backend/pdp/indicators/CLAUDE.md` | Family list + the "compute once, never recompute" rule |
| `backend/strategies/directional_strangle_nifty.yaml` | `periods: [9, 20, 50, 100]` at `:20` — the actual cause of `--` |
| `backend/backtest/configs/strangle_nifty_hedged.yaml` | Must move in lockstep or live/backtest diverge |
| `backend/tests/indicators/test_warmup.py` | `:251-291` import the constants this change deletes |

## Key facts established during investigation
- **EMA(200) is not configured anywhere.** All three live configs stop at period 100. Warmup depth
  was never the cause; the root `CLAUDE.md` troubleshooting row saying otherwise is wrong.
- `_TF_WARMUP_CALENDAR_DAYS` values (15m→40, 30m→45, 1H→90) are nominally generous, but they are
  hand-maintained constants annotated ">> 200" — an assumption that breaks the moment a period grows.
- `_DEFAULT_WARMUP_CALENDAR_DAYS = 1`: a timeframe missing from the map warms up on one day of data,
  silently.
- Warmup seeds from Mongo `market_bars` and succeeds with however few bars it finds. There is no
  signal today distinguishing "converged" from "still converging".

## Related
Depends on `bar-session-anchoring`. Feeds `bias-input-completeness` (which adds the `1w` timeframe
and therefore its own depth requirement).

## Findings during implementation (2026-07-12)

- **Backtest-config EMA parity (proposal's task 2.3/2.4/1.5) does not apply as written.**
  `backend/backtest/configs/strangle_*_hedged.yaml` (`StrangleConfig`) has no `ema`/
  `suite_indicators` field at all — the strangle backtest's EMA input is a hardcoded
  9/20/50 alignment vote (`pdp/signals/bias.py TimeframeEMA`, business logic, not the
  console's period-200 concept). `StrangleConfig` (unlike the generic `sim.py`'s
  `StrategyConfig`) never had a `suite_indicators` mechanism. There is therefore no
  "live vs backtest ema periods" YAML field to diff; task 1.5's test instead guards that
  the live watchlist's `ema` periods stay a superset of the bias engine's fixed 9/20/50
  requirement (`tests/strategies/test_config_parity.py`).
- **Deduplicated live/backtest EMA→TimeframeEMA conversion.** Both sides already ran the
  identical `EMATracker` class, but each independently reimplemented the final
  "extract 9/20/50 from a values dict" conversion (`directional_strangle.py::_to_tf_ema`
  vs `strangle_loader.py::_tf_ema_at`). Factored into one shared
  `pdp.signals.bias.tf_ema_from_values()`, called by both.
- **EMA/RSI/MACD/VWMA/PeriodLevels already omitted unconverged values correctly** before
  this change (task 4 audit) — `EMATracker.update()` already filters `values` to only
  periods where `n == p` has been reached; RSI's `ma`, MACD's whole state, and VWMA's whole
  state were already gated the same way. No code change was needed for task 4.1/4.2 — the
  proposal's Cause 2 was about warmup *depth* (too few bars fetched), not a convergence bug
  in the trackers.
- **`backfill_market_bars.py` real run (2026-07-12, `WAREHOUSE_UNDERLYINGS=['NIFTY']` in
  this environment — BANKNIFTY/SENSEX are not warehoused here yet, so nothing to backfill
  for them):**

  | underlying | tf  | found (before) | found (after) | needed | action |
  |------------|-----|-----------------|----------------|--------|--------|
  | NIFTY | 15m | 1685 | 1685 (already met) | 1000 | none |
  | NIFTY | 30m | 875 | 19,903 | 1000 | rollup from dense 1m (2017-present, 572,969 bars) |
  | NIFTY | 1H | 478 | 10,658 | 1000 | rollup from dense 1m |

  1m coverage for NIFTY was already dense back to 2017 — the 30m/1H shortfall was purely
  "never rolled up that far back" (the `bar-session-anchoring` rebuild only touched the
  last ~3 months), not a missing-source-data problem. 4 dates (2021-11-04, 2022-10-24,
  2024-11-01, 2025-10-21 — Diwali Muhurat trading, an abbreviated ~1hr session) triggered
  the Dhan 1m-gap fallback and failed after retries; harmless — Muhurat's short session
  never had 375 bars to begin with, and post-rollup depth is 10-20x the requirement anyway.
- **Warmup cost (task 7):** full warmup for all three live strategies (nifty/banknifty/sensex
  x 5m/15m/30m/1H/1D, the real `strategies/*.yaml` watchlists) took **5.19s total** against
  production Mongo — well within any reasonable boot budget, not on the tick hot path. No
  synchronous/background split (task 7.2) is warranted at this depth. Confirmed no change
  to the hot path itself (warmup only touches `IndicatorEngine.seed_from_bars`, never
  `TickRouter.run`), so tick→WS p99 is structurally unaffected (task 7.3).
- **BANKNIFTY/SENSEX 30m/1H/1D still report `indicator_warmup_short`** (865/1000, 469/1000,
  445/1000 bars respectively) — expected and correctly surfaced by the new warning, not a
  bug: `WAREHOUSE_UNDERLYINGS=['NIFTY']` in this environment's `.env`, so
  `backfill_market_bars.py` only backfilled NIFTY per its spec (task 5.1: "for each
  `WAREHOUSE_UNDERLYINGS` x configured TF"). Expanding `WAREHOUSE_UNDERLYINGS` to
  BANKNIFTY/SENSEX is a production config decision outside this change's scope, not a code
  change — flagged here for whoever owns that `.env`.
- **`DHAN_ACCESS_TOKEN` in this environment is expired** (`DH-901 Invalid_Authentication`
  surfaced during the timing run above) — unrelated to this change (credential rotation is
  an ops task), but means the Dhan-fallback path could not be exercised end-to-end here
  beyond the 4 already-covered Muhurat-day attempts.

## Combined re-baseline results (2026-07-13)

Re-ran all three strangle configs over the archived baseline's exact window
(2021-06-01 → 2026-05-29) after `bar-session-anchoring` + `indicator-history-depth` +
`bias-input-completeness` all landed. Per-run logs: `strangle_20260713-113418` (NIFTY),
`strangle_20260713-113423` (BANKNIFTY), `strangle_20260713-113428` (SENSEX), all persisted to
the `backtest_runs` Mongo warehouse.

| Underlying | Net P&L | PF | Win% | MaxDD | Trades | Traded days | Halted |
|---|---|---|---|---|---|---|---|
| NIFTY (current config, `dte_max:15`) | +₹42.71L | 6.15 | 86% | ₹51,032 | 10,274 | 840 | 27 |
| NIFTY (archived baseline, no DTE filter, pre-fixes) | +₹85.60L | 5.72 | 75% | ₹71,579 | — | 1171 | 50 |
| BANKNIFTY (current config, `dte_max:15`) | +₹46.82L | 5.93 | 80% | ₹45,222 | 13,962 | 1176 | 14 |
| SENSEX (current config, `dte_max:15`) | +₹20.87L | 6.13 | 80% | ₹55,632 | 9,655 | 754 | 6 |

BANKNIFTY and SENSEX have no prior baseline to compare against — these are their first full
5-year runs. Only NIFTY has an archived number.

### NIFTY isolation: separating this session's fixes from the `dte_max` policy effect

The raw NIFTY comparison above conflates two independent changes: (1) this session's three
data/indicator fixes, and (2) `dte_max:15`, set in the *already-archived*, out-of-scope
`strangle-live-dte-window` change (2026-07-10, three days before this session started) — confirmed
via `git log` to be unrelated to papergapfix. To isolate the fixes' own effect, NIFTY was re-run
over the identical window with `--dte-max 400` (functionally disables the filter — real DTEs never
approach it):

| Run | Net P&L | PF | Win% | MaxDD | Traded days | Halted |
|---|---|---|---|---|---|---|
| Archived baseline (pre-fixes, no DTE filter) | +₹85.60L | 5.72 | 75% | ₹71,579 | 1171 | 50 |
| This session's fixes, DTE filter disabled (isolated) | +₹56.70L | 6.81 | 87% | ₹51,032 | 1105 | 32 |
| This session's fixes + `dte_max:15` (current canonical config) | +₹42.71L | 6.15 | 86% | ₹51,032 | 840 | 27 |

**Root cause of the residual gap**, traced and externally verified (not left as a guess):

1. **A genuine, pre-existing data gap in `option_bars`** — confirmed independently via direct Mongo
   query — NIFTY has zero expiry data 2020-12-03 → 2023-01-05 (763 days), corroborated by the
   static `data/expiry/nifty_expiries.json` calendar showing the same blackout (377+ days, itself
   only monthly-granularity through 2021). This predates papergapfix entirely. Trade days that fall
   in it get forward-mapped by `nearest_real_expiry()` (`pdp/instruments/expiry_calendar.py:76`) to
   the distant post-blackout expiry; the resulting chain lookup is empty, so `build_strangle_day`
   opens zero legs — a real but P&L-**neutral** zero-trade day. This only inflates the "traded days"
   count when `dte_max` is large; it does not bias Net P&L.
2. **~25 smaller 12-21 day gaps scattered 2023-2026** are a different animal — spot-checked against
   NSE's real calendar (confirmed Thu 2023-02-16 was a genuine NIFTY weekly expiry, absent from both
   `option_bars` and the static calendar). These are missing-ingestion weeks where the *current-week*
   contract's data was never captured, but a real, further-dated (usually monthly) contract's price
   history does cover those calendar days — so trading through them (`dte_max` disabled) is a real
   trade with real P&L, not a phantom. `dte_max:15` deliberately excludes these by the intentional
   design of `strangle-live-dte-window` ("enter only where theta decay is steepest") — a live-strategy
   policy choice, not a papergapfix bug. This is the main driver of the ₹14L gap between the isolated
   (+₹56.70L) and canonical (+₹42.71L) NIFTY runs.
3. Even after removing both the DTE-window policy effect and the (P&L-neutral) data blackout, NIFTY's
   isolated Net P&L is ~34% below the archived baseline (+₹56.70L vs +₹85.60L). PF (6.81 vs 5.72),
   win rate (87% vs 75%), MaxDD (₹51k vs ₹71.6k), and halted-days (32 vs 50) all *improved* — the
   expected signature of `bias-input-completeness` (bias now reads correct 1D Camarilla pivots
   instead of 5m) and `indicator-history-depth` (EMA200 now properly gates entries instead of trading
   on unconverged/missing state): a more accurate bias signal trades less often, at higher quality
   per trade. This is judged a real behavior change, not a regression.

### Verdict (user decision, 2026-07-13)

**Supersede.** The archived NIFTY baseline (+₹85.6L / PF 5.72 / Win 75% / MaxDD ₹71,579 / 1171
traded days, `openspec/changes/archive/2026-06-26-directional-strangle/tasks.md`) is superseded by:
- **+₹42.71L | PF 6.15 | Win 86% | MaxDD ₹51,032 | 840 traded days** — current production config
  (`dte_max:15`), what the live strategy will actually produce.
- **+₹56.70L | PF 6.81 | Win 87% | MaxDD ₹51,032 | 1105 traded days** — this session's fixes in
  isolation (DTE filter disabled), the fairest like-for-like comparison to the archived run.

BANKNIFTY (+₹46.82L / PF 5.93) and SENSEX (+₹20.87L / PF 6.13) become the first recorded baselines
for those underlyings.

The `option_bars` gap itself (blackout + ~25 small weeks) is filed separately —
`openspec/changes/option-bars-expiry-gap-backfill` — out of papergapfix's scope, since it affects
backtest data quality generally (BANKNIFTY/SENSEX likely have analogous gaps, unaudited).
