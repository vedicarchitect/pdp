# bar-session-anchoring — minimal context

Read only these to work this change.

| File | Why |
|------|-----|
| `backend/pdp/market/bars.py` | `_bar_boundary:49` (epoch-anchored), `_bar_boundary_1d:58`, `_bar_boundary_1w:72`, `BarAggregator.on_tick` |
| `backend/pdp/market/CLAUDE.md` | Hot-path latency budget; the stale `market_bars` schema to fix |
| `backend/pdp/indicators/warmup.py` | Seeds `IndicatorEngine` from `market_bars` — consumer of the rebuilt series |
| `backend/pdp/market/bar_writer.py` | Batch writer to `market_bars` |
| `backend/strategies/directional_strangle_*.yaml` | `timeframes: [5m, 15m, 30m, 1H, 1D]` — which TFs must be correct |

## Key facts established during investigation
- Session open 09:15 IST = 03:45 UTC = 225 min past midnight. 1440 is divisible by 30 and 60 but not
  by 25 — so 30m/1H are *stably* misaligned and 25m *drifts daily*.
- Measured bucket of the session-open tick: 5m→09:15, 15m→09:15, 25m→09:15/09:00/09:10/08:55 on
  consecutive days, 30m→09:00, 1H→08:30.
- 15m and 5m already coincide with the session grid, so the fix is a no-op for them. That is the
  regression test.
- 1m bars are session-aligned by construction and dense — rebuild from them, not from Dhan
  (no API quota, reproducible).
- `market_bars` is a Mongo **timeseries** collection: no in-place update, delete-then-insert only.

## Related
Blocks `indicator-history-depth` (no point backfilling mis-anchored bars) and
`bias-input-completeness`. Expect archived backtest baselines to move; re-baseline before trusting
any later strategy change.

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
