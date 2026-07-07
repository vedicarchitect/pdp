# Tasks — live-pnl-trade-ledger-and-journal

> Implementation contract. Every task states the exact file, symbol, and expected behaviour so
> any implementer produces the same result. Line numbers are as-of change authoring and may
> drift — always locate by symbol name. Money is `Decimal` in Python, formatted `₹` in Flutter.
> Everything user-facing breaks out **per index** (NIFTY / BANKNIFTY / SENSEX).

## 1. Enriched leg-close events (backend — single source of the ledger)

- [ ] 1.1 In `pdp/strategies/directional_strangle.py`, add an exit-fields helper
  `_leg_exit_fields(leg: OpenLeg, exit_px: float, reason: str) -> dict` that returns:
  `entry_price` (`float(leg.entry_price)`), `exit_price` (`exit_px`), `lots` (`leg.lots`),
  `entry_time` (`leg.entry_time.isoformat()` or None), `exit_time`
  (`datetime.now(tz=_IST).isoformat()`), `pnl` (see 1.2), `opt_type`, `strike`,
  `is_hedge` (`leg.is_hedge`), `expiry` (resolved per 1.3), and `symbol` (resolved per 1.4).
- [ ] 1.2 P&L sign convention MUST match `_compute_unrealized` exactly: for a **short** leg
  `pnl = round((entry_price − exit_price) * lots * self._lot_size, 2)`; for a **hedge/momentum
  long** `pnl = round((exit_price − entry_price) * lots * self._lot_size, 2)`. Add a unit test
  asserting a sold-at-100 / bought-back-at-40 short with 2 lots × lot_size returns a positive
  pnl equal to `(100−40)*2*lot_size`, and the hedge case is inverted.
- [ ] 1.3 Resolve `expiry` for the closed leg. `OpenLeg` has no `expiry` field today — add
  `expiry: date | None = None` to the `OpenLeg` dataclass and populate it at open time in
  `_open_short` / `_open_hedge` / `_open_bucket` (the expiry is already resolved there via
  `nearest_expiry`/`_instrument_for_strike`). Do NOT re-query at close time.
- [ ] 1.4 Resolve the human `symbol` via
  `pdp.instruments.symbols.symbol_for(underlying, expiry_date, strike, option_type)` (pure,
  no I/O) when `expiry` is known; fall back to `pdp.instruments.service.get_by_id(sid)` →
  `resolve_symbol(...)` only if `expiry` is missing. Never block the tick hot path on a DB
  round-trip — if resolution needs I/O and none is cached, emit `symbol=None` and let the
  `/strangle/trades` endpoint resolve lazily (see 3.4). Symbol format is
  `NIFTY-Jul2026-24300-CE` (from `symbols.symbol_for`).
- [ ] 1.5 Wire `_leg_exit_fields` into every terminal close emit:
  `_close_short_leg` (`LEG_CLOSE`, `:979`), `_close_hedge_leg` (`LEG_CLOSE`, `:994`),
  the `TAKE_PROFIT` emit (`:468`), `STOP_ALL` (`:488`), and `STOP_HALF` (`:480`, note: partial
  — carries `remaining` lots and a `pnl` for the closed half only). `_close_all` /
  `square_off` (`:955-958`) closes legs via `_close_short_leg`/`_close_hedge_leg`, so those
  already inherit the enriched fields — verify the `SQUARE_OFF`/`DAY_LOSS_CAP` summary event
  also carries the day's realized total.
- [ ] 1.6 `STOP_HALF` exit price is the current `ltp`; only `close_lots = leg.lots // 2` lots
  are closed, so its `pnl` uses `close_lots`, not `leg.lots`. The remaining lots stay open and
  their eventual close emits a second enriched event. The ledger pairing (task 3) MUST handle a
  single `leg_open` producing a partial `stop_half` + a later terminal close.
- [ ] 1.7 Do not change `_emit_event` (`:531`) itself — it already fans out to the daily log +
  OpenSearch via `strategy/log.py`. Only the payload dicts grow. Confirm
  `pdp/observability/sinks.py::strangle_event_doc` passes through the new fields (it maps the
  raw record; add the new fields to its projection if it whitelists keys).

## 2. Canonical live P&L, per index (backend)

- [ ] 2.1 Confirm `directional_strangle.state()` is the single P&L authority: it already
  returns `day_realized`, `day_unrealized`, `day_pnl`, `n_open_*`, `done_for_day`. Do not add a
  second P&L computation anywhere.
- [ ] 2.2 The strangle console runs one strategy instance per index (NIFTY/BANKNIFTY/SENSEX).
  `strangle_monitor` (`pdp/strategy/routes.py:388`) already gathers `state()` for all
  strategies via `states = [await s.state() for s in strategies]`. Ensure each state row
  carries its `underlying` (add `"underlying": self.underlying` to `state()` if absent) so the
  UI can group and never blends indices.
- [ ] 2.3 Add `GET /api/v1/strangle/pnl` (or extend `/strangle/stats`) returning a per-index
  breakdown: `[{underlying, day_realized, day_unrealized, day_pnl, n_open_legs, done_for_day,
  squared_off_at}]` plus a `totals` object summing across indices. `squared_off_at` is the IST
  time of the terminal `square_off`/`day_loss_cap` event for that index today (from the ledger,
  task 3), else null. This is the ONLY P&L the dashboard portfolio card + Execution tab read.

## 3. Persisted entry→exit ledger + `/strangle/trades` API (backend)

- [ ] 3.1 Add a ledger reader `pdp/strategy/trade_ledger.py` with
  `def pair_trades(events: list[dict]) -> list[dict]`: given the day's canonical events (from
  the JSONL log or OpenSearch), pair each `leg_open` to its terminal close event by
  `security_id` in time order. Terminal events: `leg_close`, `take_profit`, `stop_all`,
  `square_off`-driven closes. A `stop_half` is a partial: it reduces open lots and produces its
  own row with `partial=true`; the remaining lots pair to the later terminal close.
- [ ] 3.2 Each paired row: `{underlying, security_id, symbol, opt_type, strike, expiry, lots,
  is_hedge, entry_price, entry_time, exit_price, exit_time, pnl, reason, partial}`. Still-open
  legs (a `leg_open` with no terminal close yet) are returned with `exit_price=null`,
  `exit_time=null`, `pnl=null`, `open=true` so the UI can show them as "open" in the same table.
- [ ] 3.3 Source events: prefer reading the day's JSONL at `logs/<strategy_id>/<date>.log`
  (one JSON object per line, via `StrategyDailyLog`); if that file is absent (e.g. running
  against OpenSearch-only history), query the `strangle-events` OpenSearch index for that
  `strategy_id` + IST day. Reuse existing `pdp/observability` read helpers — do NOT add a new
  Mongo/PG store.
- [ ] 3.4 Add `GET /api/v1/strangle/trades?strategy_id=&date=` in `pdp/strategy/routes.py`
  (`strangle_router`). Default `date` = today IST; default `strategy_id` = all strangle
  strategies (loop the host's strangle instances). Response:
  `{date, by_index: {NIFTY: [...rows], BANKNIFTY: [...], SENSEX: [...]}, totals: {realized_pnl,
  n_round_trips, n_open}}`. `realized_pnl` here = sum of `pnl` over **closed** rows only.
  If a row has `symbol=null`, resolve it lazily here via `instruments` helpers before returning.
- [ ] 3.5 Unit-test `pair_trades` with a synthetic event list covering: (a) a clean
  open→take_profit round-trip, (b) an open→stop_half→stop_all sequence (one partial + one
  terminal row), (c) a still-open leg (open with no close), (d) a hedge leg open→close. Assert
  the per-index grouping and that `realized_pnl` excludes the open leg.

## 4. Journal reads the SAME ledger (backend)

- [ ] 4.1 Fix the realized-P&L bug in `pdp/journal/stats.py::compute_daily_stats`: realized
  P&L MUST be `sum(round_trip_pnl)` over **completed** round-trips only (the `acc["sell_val"]
  − acc["buy_val"] − acc["charges"]` already computed at `:69` for the round-trip guard), NOT
  the all-fills `sell_value − buy_value − total_charges` at `:58-59`. Keep
  `gross_premium_sold`/`gross_premium_bought`/`total_charges` as informational lines. An open
  short (sold, not yet bought back) MUST contribute 0 to `realized_pnl`.
- [ ] 4.2 Add a regression test in `tests/journal/test_stats.py`: a day with one open short
  (SELL 100, no BUY) MUST report `realized_pnl == 0` (today it wrongly reports the full sell
  premium). A completed round-trip (SELL 100 → BUY 40) MUST report `realized_pnl == +60*qty`
  minus charges.
- [ ] 4.3 Make the Journal's trade source the enriched ledger: the Journal detail view returns
  the same entry→exit round-trip rows as `/strangle/trades` (symbol, strike/expiry, entry→exit,
  per-trade pnl), grouped by index/strategy. Either have `journal/routes.py` delegate to the
  `trade_ledger.pair_trades` reader for strangle strategies, or have both endpoints call the
  shared pairing function — one implementation, two surfaces. Journal `realized_pnl` and the
  `/strangle/trades` `realized_pnl` for the same day+strategy MUST be equal.
- [ ] 4.4 Keep `record_fill` (`journal/service.py:80`) unchanged as the raw-fill capture; it is
  the input to `compute_daily_stats` for non-strangle strategies. The strangle ledger derives
  from strategy events, not fills — do not double-count.

## 5. Flutter — Journal currency + enriched rows

- [ ] 5.1 Add a shared currency formatter `app/lib/core/format/money.dart`:
  `String inr(num v, {int decimals = 2})` returning `₹` + Indian-grouped digits (use
  `NumberFormat.currency(locale: 'en_IN', symbol: '₹')` from `intl`, or a manual grouping if
  `intl` is not a dep — check `pubspec.yaml` first and prefer the existing dep). All money in
  the app routes through this — no inline `\$` or `Rs` anywhere.
- [ ] 5.2 In `app/lib/features/journal/presentation/journal_screen.dart`, replace the
  hard-coded `\$` at lines 150, 151, 153, 272 with `inr(...)`. `Realized P&L` and `Charges`
  stats and the per-trade `@ price` all use `inr`.
- [ ] 5.3 Render enriched trade rows from the ledger: each row shows `symbol`
  (`NIFTY-Jul2026-24300-CE`), `strike`/`expiry`, `entry→exit` prices, `lots`, and per-trade
  `pnl` (green ≥0 / red <0 via theme tokens, never inline colors). Group rows by index with a
  section header per NIFTY/BANKNIFTY/SENSEX. Open legs render with an "open" chip and no exit.
- [ ] 5.4 Update `app/lib/features/journal/domain/*` models + the journal data source to parse
  the new ledger shape (`by_index`, round-trip rows). Provide a mock impl mirroring the live
  shape (per `AppConfig.useMock` convention).

## 6. Flutter — Execution tab Today's Trades + square-off banner

- [ ] 6.1 In `app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart`, add a
  "Today's Trades" table (below/alongside the existing open-legs table) fed by
  `/api/v1/strangle/trades?date=today`, grouped by index, showing symbol / entry→exit / lots /
  pnl. Use `ListView.builder`, `const` widgets, theme P&L tokens (per app/CLAUDE.md non-negotiables).
- [ ] 6.2 Add a compact day-P&L waterfall or sparkline per index (cumulative `pnl` of closed
  rows through the day) so the square-off jump is visually explained rather than appearing as a
  flicker. Keep it lightweight (fl_chart, already a dep).
- [ ] 6.3 When a strategy's `done_for_day == true`, replace the live-MTM figure for that index
  with a "Squared off HH:MM — final ₹X" banner (HH:MM from `squared_off_at`, ₹X from that
  index's final `day_pnl`). Do not show a stale ticking MTM after square-off.
- [ ] 6.4 The per-index P&L header on the Execution tab reads from `/strangle/pnl` (task 2.3)
  only — remove any dependency on `compute_daily_stats` / journal stats for live P&L.
- [ ] 6.5 Update `app/lib/features/manage/domain/execution_models.dart` +
  `app/lib/features/manage/data/manage_repository.dart` for the new `/strangle/trades` and
  `/strangle/pnl` shapes, with mock impls.

## 7. Flutter — Live Account (Dhan) surface (read-only, walled)

- [ ] 7.1 Rename the shell nav destination `Holdings` → `Live Account (Dhan)` in
  `app/lib/features/shell/app_shell.dart` (route stays `/portfolio` or rename to
  `/live-account`; if renamed, update `app_router.dart`). Icon stays wallet-style.
- [ ] 7.2 Make the screen a two-tab surface: **Holdings** (equity/ETF — the existing
  `holdings_tab.dart`, unchanged data source `/api/v1/broker-sync/holdings`) and a new
  **Positions** tab reading `GET /api/v1/broker-sync/positions` (manual F&O/intraday). Build the
  Positions tab as a new `positions_tab.dart` mirroring the holdings-tab pattern
  (domain/data/application/presentation, live + mock sources).
- [ ] 7.3 Hard visual wall: a `● LIVE (manual)` badge (distinct accent, e.g. amber) on this
  screen; `PAPER` badge everywhere the strategy book is shown (Dashboard, Execution, Journal).
  Add a shared `AccountModeBadge` widget in `app/lib/core/` taking `mode: live | paper`.
- [ ] 7.4 Strictly read-only: no order/modify/cancel controls on the Live Account surface. Its
  numbers MUST NOT be added into the paper Dashboard / Execution / Journal P&L (they are a
  separate account book).
- [ ] 7.5 Live-subscribed display MTM (backend): add an endpoint or startup hook that
  subscribes the manual positions' security ids (from the broker_sync PG mirror) to the live
  tick feed, so the Positions tab shows real-time MTM off the same feed the strategy uses.
  Display-only — no orders, no strategy ownership. Refresh the subscribed set from the mirror
  on the broker_sync EOD sync + an on-demand `POST /api/v1/broker-sync/run` re-pull.
- [ ] 7.6 The Positions tab MTM streams over the existing portfolio/market WS (or a
  broker-positions WS if cleaner); reconnect with the standard exp-backoff `ws_client.dart`.

## 8. Verify

- [ ] 8.1 Backend: `task test` green for `tests/strategy/`, `tests/journal/`,
  `tests/strategies/` (or the strangle/ledger tests); `task lint` clean on all new/edited
  modules (pre-existing debt excluded). New unit tests from 1.2, 3.5, 4.2 pass.
- [ ] 8.2 Manual/API check: `GET /api/v1/strangle/trades?date=today` returns entry→exit rows
  with pnl grouped by index; `GET /api/v1/strangle/pnl` per-index totals reconcile with the sum
  of closed-row pnl; Journal `realized_pnl` == `/strangle/trades` `realized_pnl` for the same
  day+strategy. An open short contributes 0 to realized.
- [ ] 8.3 Flutter: Journal shows `₹` (no `$`), readable symbols, entry→exit round-trips with
  per-trade P&L; Execution tab shows Today's Trades + waterfall + square-off banner; Live
  Account (Dhan) shows Holdings + Positions with a `● LIVE (manual)` badge and no order
  controls; PAPER badge on the paper surfaces.
- [ ] 8.4 `cd app && flutter analyze && flutter test` green.
- [ ] 8.5 `openspec validate live-pnl-trade-ledger-and-journal --strict`; archive on green.
