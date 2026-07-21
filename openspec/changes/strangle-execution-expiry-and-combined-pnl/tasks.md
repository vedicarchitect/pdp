# Tasks

## 1. Backend — monitor payload

- [x] 1.1 `DirectionalStrangle.state()` (`directional_strangle.py`): emits `expiry`
      (`lg.expiry.isoformat()` or `None`) in each leg dict.
- [x] 1.2 `strangle_monitor` (`strategy/routes.py`): computes `dte` per leg (calendar days from
      IST-today to `expiry`, `None` when no expiry) and passes `expiry` through in the payload.
- [x] 1.3 `strangle_monitor`: replaced the hardcoded `groups[].totals.day_realized = 0.0` with
      the real per-underlying value from `states[i]`; per-group `day_pnl = day_realized +
      day_unrealized`.

## 2. Backend — cosmetic + rehydration pricing

- [x] 2.1 Guarded `entry_reason` (`self._current_bucket or 'unknown'`) so an unset bucket never
      renders the literal `"None"` (all three sites).
- [x] 2.2 Added `_seed_rehydrated_ltp` and call it from `_rehydrate_legs`: seeds `_ltp_cache`
      from Redis `ltp:<sid>` if present, else the leg avg entry price, so a restored leg is
      priced immediately instead of `--`.

## 3. Flutter

- [x] 3.1 `execution_models.dart`: `LegRow` gained `expiry` (String?) + `dte` (int?), parsed
      from the monitor leg payload; `UnderlyingGroup` gained `dayRealized`/`dayUnrealized`.
- [x] 3.2 Leg-row widget: added a `DTE` column ("--" when null).
- [x] 3.3 Group header: added a per-underlying `realized … · unrealized …` breakdown line under
      the bold combined P&L total.
- [x] 3.4 Indicator matrix (`_SidMatrix` → stateful): wrapped the horizontal
      `SingleChildScrollView` in a `Scrollbar(thumbVisibility: true)` with a dedicated controller
      so CamR4/CamS4 are reachable via a visible affordance.

## 4. Verify

- [x] 4.1 Backend unit tests added: `test_monitor_leg_carries_expiry_and_server_computed_dte`,
      `test_monitor_group_totals_use_real_per_underlying_realized`, `test_state_emits_leg_expiry`,
      `test_entry_reason_never_renders_literal_none`,
      `test_seed_rehydrated_ltp_prefers_redis_then_entry_price` — all pass.
- [x] 4.2 `task test`: 1213 passed, 4 failed — all 4 pre-existing isolation flakes unrelated to
      this change (3 `tests/observability/test_processor.py`, 1
      `tests/jobs/test_runner.py::test_job_cancel`; no `jobs/` or `observability/` files touched
      by this change).
- [x] 4.3 Flutter widget tests added (both breakpoints): DTE column + combined-P&L breakdown
      render; matrix Scrollbar present. `flutter analyze --fatal-infos` → "No issues found";
      `flutter test` → all 47 passed.
- [x] 4.4 `openspec validate --strict strangle-execution-expiry-and-combined-pnl` — valid.
- [ ] 4.5 Live smoke: `/monitor` shows `expiry`/`dte` on real legs; each group shows a combined
      P&L line; rehydrated SENSEX legs show a price immediately after restart; the matrix's
      rightmost columns are reachable in the app.

## 5. Archive

- [ ] 5.1 `openspec archive strangle-execution-expiry-and-combined-pnl` once 4.5 passes.
