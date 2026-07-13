# bias-input-completeness — minimal context

Read only these to work this change. **Do not start until `bar-session-anchoring` and
`indicator-history-depth` are applied.**

| File | Why |
|------|-----|
| `backend/pdp/strategies/directional_strangle.py` | `_build_bias_inputs:689-727` — `pivots(sid,"5m")` at `:696`, `pivots(sid,"1w")` at `:700`, `get_pcr` at `:708` |
| `backend/pdp/signals/bias.py` | `BiasInputs:59-75`, `BiasWeights:96-111`, `score_bias:279`, vote table `:297-301` |
| `backend/pdp/strategy/host.py` | Strategy load — where the satisfiability check goes |
| `backend/pdp/settings.py` | `OPTIONS_UNDERLYINGS:87`, `WAREHOUSE_UNDERLYINGS:113` |
| `backend/strategies/directional_strangle_nifty.yaml` | `timeframes:17`, `indicators:18-27`, weights `:91-98` |
| `backend/pdp/indicators/engine.py` | Trackers exist only for configured `(sid, tf)` pairs |

## Key facts established during investigation
- `cam_daily` reads pivots on **`5m`** — a five-minute pivot weighted as a daily level.
- `cam_weekly` reads `1w`, which **no watchlist declares** → always `None`, `w_cam_weekly: 1.0` is dead.
  The code comment at `:699` describes wiring that does not exist.
- `OPTIONS_UNDERLYINGS` is `["NIFTY","BANKNIFTY"]` and **is present in `backend/.env`** — the `.env`
  value wins, so editing `settings.py:87` alone changes nothing. (`BROKER_SYNC_ENABLED`, by contrast,
  is absent from `.env`, which is why the code default governed there.)
- `WAREHOUSE_UNDERLYINGS` defaults to `["NIFTY"]` only.
- `score_bias` treats a null vote as an abstention and renormalises. A weight on a permanently-absent
  input is indistinguishable from a neutral market — that is the structural bug; the three specific
  wiring faults are instances of it.
- Two of the three dead inputs pull toward neutral, and `neutral: [3, 3]` is the most-traded bucket.
  The live strategy has been more neutral than its backtest.

## Related
`[[directional_strangle]]`, `[[live_backtest_parity]]`. Re-baseline the backtests afterwards and
compare the **bucket histogram**, not only P&L.

## Findings during implementation (2026-07-12)

- **`period_levels` on `5m` is already correct — no code change (task 2.2).**
  `PeriodLevelsTracker.update()` accumulates day/week/month high-low from whatever bars it's
  fed and freezes at the boundary. The day's high computed from 5m bars equals the day's high
  computed from 1D bars (same underlying max, finer granularity) — there's no per-timeframe
  assumption in the freeze logic. Verified by direct read, not assumption.

- **Backtest-config `1w` (task 3.2) doesn't apply, for a different reason than `cam_daily`.**
  `pdp/backtest/strangle_loader.py` never went through the `IndicatorEngine`/watchlist path at
  all for Camarilla — it computes `cam_daily`/`cam_weekly` directly from resampled 1m spot bars
  (`_camarilla(_hlc(prior1))` and `_camarilla(_hlc(_prior_week_1m(...)))`), correctly, using the
  true prior day/week's HLC. **The backtest was never wrong here — only live was**, which is
  exactly the "live is not trading the strategy that was backtested" framing from the proposal's
  Why section, just more precisely: the divergence was live-only, not a live/backtest parity gap
  that needed closing on both sides.

- **Two real, pre-existing bugs found and fixed while wiring `1w` (task 3.3), both affecting
  pivots generally, not just weekly:**
  1. `warmup.py::_warm_one`'s prior-period HLC derivation filtered bars by
     `bar_time >= yesterday`, a comparison that only makes sense for sub-daily bars. A
     Monday-anchored `1w` bar's timestamp is never `>=` yesterday, so it always fell through to
     a `bars[-10:]` fallback and aggregated **up to 10 prior weeks'** high/low together instead
     of using the single most-recently-completed week's own HLC. Fixed: when
     `_TF_SESSION_BARS[tf] == 1` (one bar = one whole period — true of both `1D` and `1w`), the
     prior period is simply `bars[-1]`.
  2. `IndicatorEngine.seed_prior_session_pivots` mutated the `PivotTracker`'s internal `_state`
     via `seed_prior_hlc()` but never refreshed the cached `Snapshot` that
     `get_pivots()`/`get_snapshot()` actually read from. Since this correction runs *after*
     `seed_from_bars` already cached a snapshot from the historical bars, the correction was
     silently invisible to every consumer until the next live bar closed — for **every**
     timeframe with `pivots` configured (5m/15m/30m/1H/1D), not just the new `1w` entry. This
     means `cam_daily` would have been subtly stale (one extra day back) even after the `1D`
     read fix in task 2.1, had this not been caught. Fixed: `seed_prior_hlc()` now returns the
     new state, and `seed_prior_session_pivots()` uses it to `dataclasses.replace()` the cached
     `Snapshot`. Regression-guarded by
     `tests/indicators/test_warmup.py::test_weekly_pivot_seeds_from_single_prior_week_not_aggregate`.

- **`1w` needed a second watchlist entry, not an addition to the existing one.**
  `WatchlistEntry.indicators` applies uniformly to every timeframe in that entry's
  `timeframes` list — there's no per-timeframe indicator config. Adding `1w` to the main entry
  (which carries `ema periods:[9,20,50,100,200]`, `supertrend`, `psar`, `vwap`) would have
  configured EMA(200) etc. on **weekly** bars too — needing ~19 years of weekly history to
  converge, and disarming the strategy at *every* startup via `StrategyHost.start()`'s
  `is_warm(sid, "1w", min_bars=200)` check (200 weekly bars ≈ 4 years; BANKNIFTY has ~3.4yr,
  SENSEX ~2.5yr). Fixed with a second watchlist entry for the same `security_id`:
  `timeframes: [1w]`, `indicators: [{family: pivots}]` only — `configure_suite` unions families
  per `(sid, tf)`, so this cleanly adds just weekly pivots. Also exempted `tf == "1w"` from the
  200-bar disarm check in `host.py` (weekly pivots seed from one completed week, not a bar-count
  convergence proxy — see bug #1 above for what "seed" actually means here).

- **Architectural redirect on `OPTIONS_UNDERLYINGS`/`WAREHOUSE_UNDERLYINGS` (task 4, explicit
  user decision, 2026-07-12):** *"keep credentials and general settings only in .env, rest all
  config keep it separately based on strategy."* Rather than adding `SENSEX` to two
  hand-maintained global lists (the original plan, and the literal cause of this incident — the
  poller's underlying list had silently drifted from what strategies actually needed), both
  settings are **removed**. `pdp.strategy.registry.strategy_underlyings(strategies_dir)` derives
  the underlying set from every loaded strategy YAML's `params.underlying`;
  `OptionsChainPoller`/`WarehouseService` now take an explicit `underlyings` constructor arg
  computed this way. This closes the entire bug class (a strategy's own config declaring an
  underlying its infra can't see) rather than patching the one instance a proposal author
  happened to find. Spec delta: `specs/multi-index-warehouse/spec.md` (MODIFIED — the
  "Configurable warehouse underlyings" requirement no longer names a settings key).
  Consequence for `w_pcr`'s satisfiability check: since any strategy declaring
  `params.underlying: X` automatically causes `strategy_underlyings()` to include `X`, the
  `w_pcr` branch can now only fail on a genuine derivation bug or a data-inconsistency between
  the check-time and poller-configuration-time scans — not on the "someone forgot to edit
  `.env`" failure mode this whole change exists to fix. That's the intended outcome, not a
  weakness: the check is now a structural consistency guard rather than a manual-sync reminder.

- **`_weights_from_params` renamed to `weights_from_params`** (dropped the leading underscore) —
  pyright's `reportPrivateUsage` correctly flagged the original private name being imported
  across the `directional_strangle.py` → `host.py` module boundary. It's genuinely
  cross-module shared code (the whole point of extracting it was to give `on_init` and the
  host-level satisfiability check identical defaults), so it should never have been private.

- **DHAN_ACCESS_TOKEN still expired in this environment** (same finding as
  `indicator-history-depth`) — task 4.4/4.5 (confirm the SENSEX chain poller actually starts and
  check Dhan rate-limit load) could not be verified end-to-end live. Confirmed via code read
  that `OptionsChainPoller.start()` logs `options_poller_started` with the resolved
  `underlyings` list, so this is a one-line log check the moment credentials are live.

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
