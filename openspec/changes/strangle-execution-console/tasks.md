## 1. Parity — vote logging + leg status heartbeat

- [x] 1.1 In `on_bar`, pass `result.votes` into the existing `bias_evaluated` log call as a `votes=` kwarg (BiasResult already exposes it)
- [x] 1.2 After `bias_evaluated`, emit `leg_status` event via `emit_strangle_event` with a `legs` list: each entry has `security_id`, `opt_type`, `strike`, `lots`, `entry_price`, `ltp` (from `_ltp_cache`), `mtm` (ltp−entry × lots × lot_size, nullable)

## 2. Parity — rollup on premium decay

- [x] 2.1 Add params `roll_trigger_prem` (default 20) and `roll_target_min_prem` (default 50) to `on_init`
- [x] 2.2 In `on_tick`, after the existing TP/stop checks for a short leg, add: if `ltp < roll_trigger_prem` and not already being rolled, call `_roll_leg(leg)` (new method)
- [x] 2.3 Implement `_roll_leg`: close old short + matching hedge, `resolve_otm_option` for next strike with premium ≥ `roll_target_min_prem`, open new short + hedge, emit `rolled` event

## 3. Parity — stop-gate re-entry cooldown

- [x] 3.1 Add `_stop_gate: dict[str, dict]` to `on_init` (keyed by `opt_type`: `{exit_px, sid, n_below}`)
- [x] 3.2 After `stop_half`/`stop_all` fires in `on_tick`, record `_stop_gate[opt_type] = {exit_px: ltp, sid, n_below: 0}`
- [x] 3.3 On each 5m bar (before `_open_short`), for each gated `opt_type`: get LTP from `_ltp_cache`; if `ltp < exit_px` increment `n_below`, else reset to 0; clear gate when `n_below >= 3`; emit `stop_gate_wait` event while gate is active
- [x] 3.4 Gate `_open_short`: at start of `_open_short`, if `opt_type in _stop_gate`, log `stop_gate_wait` and return without placing
- [x] 3.5 `_stop_gate.clear()` in `_maybe_reset_day` and after `_close_all`

## 4. Parity — weekly Camarilla + live PCR

- [x] 4.1 In `on_init`, subscribe `self.sid` on `"1w"` via `ctx.market.subscribe(self.sid, self.index_segment)` (same segment, weekly timeframe)
- [x] 4.2 In `_build_bias_inputs`, replace `cam_weekly=None` with `_to_cam(ind.pivots(self.sid, "1w"))` (returns None gracefully if not warmed); emit `cam_weekly_missing` debug once per session on first None
- [x] 4.3 Resolve PCR source in `on_init`: try `ind.pcr(self.sid)` — if the method exists, use it; otherwise fall back to reading `OptionsChainPoller.latest_pcr()` if accessible from `ctx`; if neither, keep `pcr=None`
- [x] 4.4 In `_build_bias_inputs`, replace `pcr=None` with the resolved PCR value

## 5. Parity — indicator timeframe key audit

- [x] 5.1 At the end of `on_init`, call `ind.ema(self.sid, tf)` for `"5m"`, `"15m"`, `"1h"` and collect which returned non-None; emit `strategy_warmup_check` info with `warmed_timeframes` list
- [x] 5.2 For any timeframe that returned None, emit `strategy_warmup_warning` with the missing timeframe name

## 6. Canonical log schema

- [x] 6.1 Add `StrangleEventType` StrEnum to `backend/pdp/strategy/log.py` with values: `leg_open`, `leg_close`, `take_profit`, `stop_half`, `stop_all`, `day_loss_cap`, `rolled`, `stop_gate_wait`, `bucket_change`, `bias_evaluated`, `leg_status`, `square_off`
- [x] 6.2 Add `emit_strangle_event(ctx, event_type: StrangleEventType, **fields)` helper: calls `ctx.log.info(event_type, **fields)` AND `ctx.daily_log.write({event_type: event_type, **fields, ist_time: ...})` if `ctx.daily_log` exists
- [x] 6.3 Replace all ad-hoc `ctx.log.info(...)` calls in `DirectionalStrangle` action methods with `emit_strangle_event(...)`, adding canonical base fields (`strategy_id`, `snapshot_date`, `ist_time`, `underlying`, `score`, `bucket`)

## 7. In-memory execution state + LTP cache

- [x] 7.1 Add `_ltp_cache: dict[str, float]` to `on_init` (keyed by `security_id`)
- [x] 7.2 In `on_tick`, update `_ltp_cache[sid] = ltp` for every option tick received
- [x] 7.3 Add `_activity: collections.deque[dict]` (maxlen=200) to `on_init`
- [x] 7.4 In `emit_strangle_event`, append the event dict to `_activity` after logging
- [x] 7.5 Add `state() -> dict` method returning: `mode`, `strategy_id`, `bucket`, `score`, `legs` (full leg dicts with LTP from `_ltp_cache`), `day_realized`, `day_unrealized`, `day_pnl`, `done_for_day`, `vix_now`, `n_open_legs`, `started_at`

## 8. Execution console REST API

- [x] 8.1 Add `StrangleState`, `StrangleLeg`, `StrangleActivityEvent` msgspec structs to `backend/pdp/strategy/schemas.py`
- [x] 8.2 In `backend/pdp/strategy/routes.py`, add helper `_get_strangle(app_state)` → finds the first loaded `DirectionalStrangle` instance via `StrategyHost.strategies` or raises HTTPException 404
- [x] 8.3 Add `GET /api/v1/strangle/status` route: calls `strategy.state()`, returns mode/bucket/score/done_for_day/vix_now/started_at/n_open_legs/day_pnl
- [x] 8.4 Add `GET /api/v1/strangle/legs` route: returns `strategy.state()["legs"]` as a list with entry_price, ltp (nullable), mtm (nullable), opt_type, strike, lots, is_hedge
- [x] 8.5 Add `GET /api/v1/strangle/activity?n=50` route: returns last `min(n, 200)` events from `strategy._activity`, newest-first
- [x] 8.6 Add `GET /api/v1/strangle/stats` route: returns day_realized, day_unrealized, day_pnl, trade_count, open_pe_lots, open_ce_lots, open_hedge_lots
- [x] 8.7 Mount the four new routes under the existing strategy router in `main.py` (or confirm they're auto-included via the existing `include_router(strategy_router)`)

## 9. Tests

- [x] 9.1 Unit test: `bias_evaluated` log event includes `votes` dict on every 5m bar
- [x] 9.2 Unit test: `leg_status` event emitted after every `bias_evaluated` (including when flat)
- [x] 9.3 Unit test: `_roll_leg` fires when `ltp < roll_trigger_prem` and emits `rolled` event
- [x] 9.4 Unit test: stop-gate blocks `_open_short` for 3 bars then clears; `stop_gate_wait` emitted while gated
- [x] 9.5 Integration: `GET /api/v1/strangle/status` returns 200 with `bucket` and `mode` fields
- [x] 9.6 Integration: `GET /api/v1/strangle/activity` returns events newest-first, respects `n` cap

## 10. RUNBOOK + parity check procedure

- [x] 10.1 RUNBOOK §18: paper mode startup checklist (task to run, env vars, how to confirm `bias_evaluated` on first 5m bar)
- [x] 10.2 RUNBOOK §19: weekly same-day parity check — run `task backtest:strangle -- --from <date> --to <date> --trace`, diff `status.log` vs live `bias_evaluated` lines for the same date
- [x] 10.3 RUNBOOK §20: canonical event types reference and how to read the daily activity log

## 11. Validation + archive

- [x] 11.1 `openspec validate strangle-execution-console --strict` passes
- [x] 11.2 Archive `live-directional-strangle-paper` (superseded): `openspec archive live-directional-strangle-paper`
- [ ] 11.3 Owner-run: paper session on next trading day — confirm `bias_evaluated` + `leg_status` log on every 5m bar; confirm `GET /api/v1/strangle/status` returns live bucket; confirm rollup fires at least once within the week
