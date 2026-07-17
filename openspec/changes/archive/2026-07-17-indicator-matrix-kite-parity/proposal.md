# indicator-matrix-kite-parity

## Why

The Execution Console's **Indicator Matrix** disagreed with the user's Kite/Zerodha charts for
NIFTY on 2026-07-13:

1. **5m EMA9/EMA20 stale** — PDP showed ~24103/24126 (fast EMA below slow, in a rising tape) while
   Kite showed ~24213/24214 near the live ~24211 print.
2. **PMH wrong** — the level chip showed `PMH=24361`; the true prior-calendar-month high is
   `24261.6`.
3. **Camarilla not visible when the panel is maximized**, and its values were never validated
   against Kite's on-chart `Pivots:R4/R3/S3/S4`.

Root-cause diagnostics (read-only Mongo, 2026-07-14) confirmed three independent defects, all
traced to the same class of problem — **HLC/window handling that doesn't honor the session-anchored
[09:15, 15:30) IST convention** already established by the archived `bar-session-anchoring` change:

- **PMH/Camarilla-monthly:** `levels_store.py`'s `_fetch_month_hlc` pads its window
  (`-6h`/`+24h`/`+30h`) and aggregates `$max` over a mixed `{"1D","1m"}` set. This pulls in an
  out-of-session pre-open print — a real cluster of prints at `2026-06-29 03:30-03:41 UTC`
  (09:00-09:11 IST, pre-open auction), peak `high=24361.1` — inflating PMH by ~100 points. The real
  June high (24261.6) is both the stored `1D` bar max and the legitimate 1m high on 2026-06-25.
  Daily/weekly Camarilla source HLC are correct; only monthly (and hence the 1D-row Camarilla and
  PMH/PML) is wrong. `backfill_levels.py` only computes daily+weekly (no monthly) and uses a third,
  independently-hand-rolled window, so the monthly path can't even be verified/rebuilt offline
  today.
- **Stale EMA/PSAR:** NOT a seed-data-quality bug — it's a **coverage gap**. NIFTY `market_bars`
  for 2026-07-13 has a full session of `1m` (376 bars) but 5m/15m/30m/1H aggregation stalled ~40
  minutes into the session (5m froze at 09:55 IST, 30m closed only its first bucket, 1H never
  closed one) and never resumed. `BarAggregator` (`pdp/market/bars.py`) is instantiated fresh at
  process startup (`pdp/runtime/groups.py:356`) with no replay/catch-up from the 1m bars already in
  Mongo — a live-process restart mid-session (see `dev_reload_scoping`/`task_dev_reload_conflict`
  memory) permanently loses that session's higher-TF bars unless someone backfills them.
  `warm_up_indicator_engine` can only seed from what's actually persisted, so the EMA/PSAR trackers
  stay frozen at whatever they last converged to. `scripts/backfill_market_bars.py` (derives
  15m/30m/1H from the dense 1m series) already exists and is the correct remediation — this is a
  rerun, not a code fix, though the underlying "no catch-up on restart" gap is worth hardening.
- **Camarilla math is correct** — `_compute_pivots` (`pivots.py`) matches Kite's own on-chart
  values exactly once fed the right HLC. The visibility bug is a fixed 440px `SizedBox`
  (`strategy_execution_tab.dart:108`) clipping the last of 13 DataTable columns when maximized.

Two scope additions confirmed with the user during investigation:

- The user trades **three SuperTrend variants** overlaid on Kite (`ST(10,2)`, `ST(10,3)`,
  `ST(3,1)`), but the matrix computes and shows only one engine-wide ST.
- Alongside the NIFTY index, show the same indicator suite for **NIFTY ATM CE and ATM PE options**,
  in both the app matrix and `scripts/trade_day.py monitor`. `option_bars` (1m, rolling ATM±band)
  already exists but is never fed to `IndicatorEngine` or served to either surface.

## What Changes

- Unify `levels_store.py`'s `_fetch_1d_hlc`/`_fetch_week_hlc`/`_fetch_month_hlc` and
  `backfill_levels.py` onto **one shared, session-anchored HLC helper**: per-trading-day
  `[09:15, 15:30)` IST windows aggregated from **1m only** (never a mixed `{"1D","1m"}` `$max`),
  falling back to a stored `1D` bar only when 1m is absent for that day. Add monthly support to
  `backfill_levels.py` so PMH/PML/Camarilla-monthly are reproducible and verifiable offline.
- Recompute NIFTY `index_levels` (daily/weekly/monthly) with the corrected helper; verify
  `PMH == 24261.6` and Camarilla R4/R3/S3/S4 (all three periods) match Kite's on-chart `Pivots:*`.
- Backfill the 2026-07-13 (and any other gappy day's) 5m/15m/30m/1H `market_bars` from the complete
  1m series via `scripts/backfill_market_bars.py`, then re-warm the engine; verify live 5m/15m
  EMA9/20 track within a few points of Kite.
- Compute and serve **three SuperTrend variants** — `ST(10,2)`, `ST(10,3)`, `ST(3,1)` — per
  `(security_id, timeframe)`, reusing the existing `SuperTrendTracker` (unchanged), replacing the
  single engine-wide ST column in the matrix and Redis snapshot.
- Add an on-demand, read-side indicator suite for **NIFTY ATM CE/PE**: resolve the current ATM
  strike (`resolve_otm_option(..., otm_steps=0)`), aggregate that strike's `option_bars` 1m to the
  matrix timeframes with the same session-anchored rollup, and run EMA/RSI/PSAR/ST×3/VWAP/VWMA over
  them. Serve as two extra rows (`NIFTY_ATM_CE`/`NIFTY_ATM_PE`) in both the monitor API and
  `trade_day.py`. Camarilla/period-levels are index-only concepts and are omitted for option rows.
  Degrade honestly (`--`) when 1m history is short — never guess.
- Flutter: render 3 ST columns/badges, the two ATM CE/PE rows, and make Camarilla
  (`CamR4`/`CamS4`) visible when the panel is maximized (relax/replace the fixed 440px `SizedBox`).
- Extend `trade_day.py`'s `_indicator_lines` into a full value-by-value validation harness — EMA,
  3×ST, PSAR, RSI, VWAP, VWMA, PDH/PDL/PWH/PWL/PMH/PML, full Camarilla per TF, and the ATM CE/PE
  rows — with an optional `--expected` per-cell diff against hand-entered Kite values. Sign off
  NIFTY first, then replicate the same fixes/validation to BANKNIFTY (SID 25) and SENSEX (SID 51).

## Impact

- Affected specs: `indicators` (SuperTrend-variant + suite-row additions), `market-data-coverage`
  (session-anchored HLC window convention — likely a delta alongside the existing
  `bar-session-anchoring` requirement).
- Affected code: `backend/pdp/indicators/levels_store.py`, `backend/scripts/backfill_levels.py`,
  `backend/pdp/indicators/engine.py`, `backend/pdp/indicators/warmup.py`,
  `backend/pdp/strategy/routes.py`, `backend/pdp/strategy/strikes.py` (reused, unchanged),
  `backend/scripts/trade_day.py`,
  `app/lib/features/manage/presentation/indicator_panel.dart`,
  `app/lib/features/manage/tabs/strategy_execution_tab.dart`.
- Out of scope (follow-up candidate): hardening `BarAggregator`/the live process to self-backfill
  missed higher-TF bars from 1m on restart, instead of relying on a manual script rerun.
