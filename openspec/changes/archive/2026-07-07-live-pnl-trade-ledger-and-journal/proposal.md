# live-pnl-trade-ledger-and-journal

## Why

Live/paper P&L is currently shown as **four disagreeing numbers** and there is **no
entry→exit trade history**, so the cockpit is untrustworthy — the single biggest blocker to
trusting the directional-strangle paper stack on its way to the backtest-proven ~₹1.35cr/5yr
target.

Concretely, verified against source:

1. **Four P&L numbers that never reconcile.** The dashboard alone shows DAY P&L, TODAY'S
   REALIZED, REALIZED, and UNREALIZED simultaneously, from two different code paths that do
   not agree:
   - The live engine `state()` (`pdp/strategies/directional_strangle.py:1008-1052`) returns
     `day_realized` / `day_unrealized` / `day_pnl` computed from `_day_realized()`
     (`:1105-1110`, baseline-adjusted realized per touched sid) + `_compute_unrealized()`
     (`:1054-1068`, live MTM of open legs). This is the trustworthy source.
   - The Journal `compute_daily_stats` (`pdp/journal/stats.py:17-88`) computes
     `realized_pnl = (sell_value − buy_value) − total_charges` over **all** fills
     (`:58-59`) — which books an open short's full sell premium as realized. Its round-trip
     guard (`:61-69`) only feeds win/loss counts, never `realized_pnl`. This is the
     −₹69,195 "morning-loss" bug and it is untested (`tests/journal/test_stats.py` checks
     `round_trips`, not `realized_pnl`).

2. **No entry→exit trade ledger.** `state().legs` returns **only currently-open** legs
   (`directional_strangle.py:1012-1034`); on close, legs are filtered out of
   `_short_legs`/`_hedge_legs` (`_close_short_leg` `:969-982`, `_close_hedge_leg` `:984-997`)
   and vanish. The `leg_close` event carries only `sid/opt_type/strike/reason` (`:979-981`,
   `:994-996`) — **no exit_price, no pnl, no exit_time, no entry_price** — even though the
   tick handler already knows both `ltp` (exit) and `leg.entry_price` at close time
   (`:457-496`). Contrast the backtest sim, which records `exit_ist`/`exit_px`/`leg_pnl`.
   The Flutter Execution tab's own "Recent events log — last 20 closed legs/exits" was never
   implemented.

3. **Square-off reads as a glitch.** At square-off / day-loss-cap, `_close_all`
   (`:942-958`) closes N legs in one 5m bar and sets `_done_for_day=True`; `on_tick` then
   early-returns (`:441`) and freezes the LTP cache. N legs with live MTM collapse to 0 legs
   with the whole day absorbed into realized, in one poll cycle — legitimate, but with zero
   UI history it looks like a flicker/glitch.

4. **Journal is not usable.** It renders `$` not `₹`
   (`app/lib/features/journal/presentation/journal_screen.dart:150,151,153,272`), shows raw
   security IDs with no strike/expiry/option-type, has no entry→exit pairing and no per-trade
   P&L, and books open positions as realized (the same −₹69,195 bug surfaced in the UI).

5. **No paper-vs-live wall.** The user's real, **manual** Dhan positions (equity holdings +
   manually-taken F&O/intraday) are not surfaced distinctly from the paper strategy book,
   risking confusion between paper and real money. The backend already exists
   (`pdp/broker_sync/`: read-only `get_holdings()`/`get_positions()`, PG mirror,
   `GET /api/v1/broker-sync/holdings` + `/positions`) and the Flutter "Holdings" tab already
   renders equity holdings (`app/lib/features/portfolio/presentation/holdings_tab.dart`).

The fix is **one persisted entry→exit trade ledger** that both the Execution tab and the
Journal read (single source of truth), a **single canonical live P&L** everywhere (the engine
`state()`), all **broken out per index** (NIFTY/BANKNIFTY/SENSEX), plus a clearly-walled,
read-only **Live Account (Dhan)** surface for the user's manual positions.

## What Changes

- **One canonical live P&L, per index.** The Execution tab and the dashboard portfolio card
  read **only** the live engine `state()` (`day_realized` / `day_unrealized` / `day_pnl`) —
  never the Journal's `compute_daily_stats` — and present it broken out per index
  (NIFTY/BANKNIFTY/SENSEX rows), not one blended figure. `compute_daily_stats` is no longer a
  P&L source for any live surface.
- **Enriched leg-close events.** `leg_close` / `take_profit` / `stop_half` / `stop_all` /
  `square_off` events carry `entry_price`, `exit_price`, `pnl`, `entry_time`, `exit_time`,
  `lots`, `expiry`, and a resolved human `symbol` (via `instruments/service.py:get_by_id` +
  `symbols.py:resolve_symbol`, e.g. `NIFTY-Jul2026-24300-CE`). No new store — these ride the
  existing `strategy/log.py` JSONL + OpenSearch sinks.
- **A per-day closed-trades ledger + API.** `GET /api/v1/strangle/trades?strategy_id=&date=`
  pairs each `leg_open` with its terminal close event (by security_id) from the persisted
  log, returning full entry→exit round-trips with per-trade P&L, **grouped by index**.
- **Journal reads the SAME ledger.** The Journal's trade source becomes the enriched
  round-trip ledger; realized P&L is derived from **matched round-trips only** (killing the
  open-as-realized −₹69,195 bug). A separate settled-charges line remains, but no phantom
  realized.
- **Flutter: ₹ + readable rows + Today's Trades + square-off banner.** `journal_screen.dart`
  uses `₹` via a shared formatter and renders enriched rows (symbol, strike/expiry,
  entry→exit, per-trade P&L). The Execution tab gains a "Today's Trades" table (alongside the
  open-legs table) and a small day-P&L waterfall; at `done_for_day` it shows a
  "Squared off HH:MM — final ₹X" banner instead of a stale live MTM.
- **Live Account (Dhan) surface, read-only, walled off.** The existing "Holdings" nav
  destination becomes "Live Account (Dhan)" with two tabs — Holdings (equity, existing) and a
  new Positions tab (manual F&O/intraday from `/api/v1/broker-sync/positions`). A hard
  `● LIVE (manual)` badge distinguishes it from `PAPER` everywhere else; it is strictly
  read-only (no order controls) and its figures never blend into the paper Dashboard /
  Execution P&L. The manual positions' security ids are subscribed to the live tick feed for
  real-time MTM (display-only), refreshed from the broker_sync mirror + on-demand re-pull.

## Impact

- **New specs:** `live-trade-ledger` (the persisted entry→exit ledger + `/strangle/trades`
  API, grouped by index), `live-account-surface` (read-only Live Account (Dhan) Positions +
  Holdings, LIVE/PAPER wall, live-subscribed display MTM).
- **Modified specs:** `paper-journal` (realized P&L from matched round-trips; Journal reads
  the enriched ledger), `strangle-execution-console` (canonical per-index live P&L; Today's
  Trades; square-off banner), `directional-strangle` (leg-close/TP/stop events carry
  entry/exit/pnl/symbol).
- **Affected backend code:** `pdp/strategies/directional_strangle.py` (enriched close events,
  symbol resolution), `pdp/strategy/routes.py` (new `/strangle/trades` endpoint + ledger
  pairing), `pdp/strategy/log.py` (event fields; sinks reused), `pdp/journal/stats.py`
  (realized from round-trips), `pdp/journal/service.py` + `routes.py` (ledger-backed trade
  source), `pdp/instruments/{service.py, symbols.py}` (reused for enrichment),
  `pdp/broker_sync/routes.py` (reused; add live-MTM subscription of manual position sids).
- **Affected Flutter code:** `app/lib/features/journal/presentation/journal_screen.dart`
  (₹ + enriched rows), `app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart`
  (Today's Trades + waterfall + square-off banner), `app/lib/features/manage/domain/execution_models.dart`,
  `app/lib/features/manage/data/manage_repository.dart` (trades endpoint), a new
  `app/lib/features/portfolio/` Positions tab + LIVE/PAPER badge, `app/lib/features/shell/app_shell.dart`
  (Holdings → Live Account (Dhan) label), a shared ₹ currency formatter in `app/lib/core/`.
- **Reuses (does not reinvent):** the engine `state()` P&L math, the `strategy/log.py` JSONL +
  OpenSearch sinks, `instruments` symbol-resolution helpers, the `broker_sync` read-only Dhan
  client + PG mirror + endpoints, and the live tick feed / WS hub. No new persistence store is
  introduced for the ledger — it is derived from the existing per-day event log.
- **Out of scope:** any order placement or modification on the Live Account surface (strictly
  read-only); MCX tiles (deferred earlier); the backtest-vs-paper convergence measurement
  (that is Change C).
