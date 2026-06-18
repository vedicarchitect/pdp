## 1. Settings & dependencies

- [x] 1.1 Add all `EVENTS_*` settings to `src/pdp/settings.py`: `EVENTS_ENABLED`, `EVENTS_SPOT_TIMEFRAMES`, `EVENTS_WATCH_LEVELS`, `EVENTS_OTM_DISTANCE_PTS`, `EVENTS_MTM_SWING_INR`, `EVENTS_TRAIL_GIVEBACK_PCT`, `EVENTS_OI_BUILDUP_PCT`, `EVENTS_PCR_BANDS`, `EVENTS_GEX_WALL_PTS`, `EVENTS_CONFLUENCE_MIN`, `EVENTS_CONFLUENCE_BAND_PTS`, `EVENTS_DELTA_NEUTRAL_BAND`, `EVENTS_POSITION_SYNC_SECONDS`, `EVENTS_COOLDOWN_SECONDS`, `EVENTS_TTL_DAYS`, `EVENTS_PUSH_ENABLED`, `EVENTS_PUSH_MIN_SEVERITY`, `EVENTS_VAPID_PUBLIC_KEY`, `EVENTS_VAPID_PRIVATE_KEY`, `EVENTS_VAPID_SUBJECT`, `EVENTS_STATS_INTERVAL_SECONDS`
- [x] 1.2 Add `pywebpush` to `pyproject.toml` dependencies; run `uv lock`
- [x] 1.3 Add `events` MongoDB collection (TTL on `ts` = `EVENTS_TTL_DAYS`) init to `src/pdp/mongo/collections.py`

## 2. period_levels indicator family

- [x] 2.1 Create `src/pdp/indicators/period_levels.py` — `PeriodLevelsState` (pdh/pdl/pwh/pwl/pmh/pml + boundary keys) and `PeriodLevelsTracker.update(...)` + `seed_prior_levels(...)`
- [x] 2.2 Register `period_levels` in `src/pdp/indicators/registry.py`
- [x] 2.3 Add `period_levels: PeriodLevelsState | None = None` to `Snapshot` in `src/pdp/indicators/snapshot.py`
- [x] 2.4 Add `get_period_levels(sid, tf)` to `IndicatorEngine`; add `"period_levels"` to `_SUITE_FAMILIES` in `src/pdp/indicators/engine.py`
- [x] 2.5 Seed `period_levels` in `src/pdp/indicators/warmup.py` from MongoDB `market_bars` (trailing week + month aggregation)
- [x] 2.6 Add `period_levels(sid, tf)` accessor to `IndicatorReader` in `src/pdp/strategy/context.py`
- [x] 2.7 Tests: `tests/indicators/test_period_levels.py` — week/month boundary freeze, seeding, snapshot exposure, IndicatorReader access
- [x] 2.8 Verify: `task typecheck` — no errors; `pytest tests/indicators/ -v` — all pass

## 3. Daily bar aggregation (1D timeframe)

- [x] 3.1 Add `1D` daily-bar aggregation to `src/pdp/market/bars.py` — extend `BarAggregator` to close a daily bar at session end; add `"1D"` to the TF interval map and warmup seed paths
- [x] 3.2 Verify: daily `Snapshot` produced after session close with correct OHLCV

## 4. Events module — core (models, store, hub)

- [x] 4.1 Create `src/pdp/events/models.py` — `EventType` enum (30+ types: SUPERTREND_FLIP, EMA_CROSS, PSAR_FLIP, MACD_CROSS, PRICE_LEVEL_CROSS, LEVEL_PROXIMITY, CONFLUENCE_ZONE, CAMARILLA_TOUCH, LEVEL_BREAK, CUSTOM_RANGE_BREAK, VOLUME_SPIKE, VOLUME_SR, GAP_OPEN, OI_WALL, OI_BUILDUP, OI_VOLUME_SPIKE, PCR_SHIFT, GEX_WALL, MAX_PAIN_PIN, IV_SHIFT, DELTA_NEUTRAL_DRIFT, BREAKEVEN_BREACH, EXPIRY_COUNTDOWN, MTM_SWING, OTM_DISTANCE, SAFE_TO_EXIT_TRAIL, SAFE_TO_EXIT_MOMENTUM, DIRECTIONAL_JUNCTION, PORTFOLIO_STATS, ORDER_FILL, SL_HIT, TARGET_HIT, KILL_SWITCH_TRIGGERED, MARGIN_WARNING, STRATEGY_SIGNAL); `Severity` enum (INFO, WARNING, ERROR, CRITICAL); `Event` dataclass; `MonitoredPosition` dataclass
- [x] 4.2 Create `src/pdp/events/store.py` — `EventStore` async writer to MongoDB `events`; `list_events(filters, limit)` for history
- [x] 4.3 Create `src/pdp/events/hub.py` — `EventsHub` WS fan-out (bounded per-client queue maxsize=100, drop-oldest on full, backfill last 50 on connect) — mirror `alerts/ws.py` pattern

## 5. Detector library

- [x] 5.1 Create `src/pdp/events/detectors/base.py` — `Detector` protocol, `DetectorState` (per-key dedup + cooldown), rolling-window helper (z-score)
- [x] 5.2 Create `src/pdp/events/detectors/levels.py` — `price_level_cross`, `level_proximity`, `camarilla_touch`, `confluence_zone` (multi-source clustering)
- [x] 5.3 Create `src/pdp/events/detectors/trend.py` — `ema_crossover` (9/20, 9/50, 20/50), `price_ema_cross`, `supertrend_flip`, `psar_flip`, `macd_cross`, `elder_impulse_change`, `elliott_wave_change`, `rsi_extreme`, `ml_signal_flip`
- [x] 5.4 Create `src/pdp/events/detectors/range_volume.py` — `level_break` (day-H/L, PDH/PDL, PWH/PWL, PMH/PML via `period_levels`), `custom_range_break`, `volume_spike` (futures z-score), `volume_sr`, `gap_open`
- [x] 5.5 Create `src/pdp/events/detectors/oi_greeks.py` — `oi_wall`, `oi_buildup`, `oi_volume_spike`, `pcr_shift` (reuse `compute_pcr`), `gex_wall` (reuse `compute_gex`), `max_pain_pin` (reuse `compute_max_pain`), `iv_shift`, `delta_neutral_drift`, `breakeven_breach`, `expiry_countdown`
- [x] 5.6 Create `src/pdp/events/detectors/position.py` — `mtm_swing`, `otm_distance`, `safe_to_exit_trail`, `safe_to_exit_momentum`, `leg_stop_proximity`, `directional_junction`
- [x] 5.7 Create `src/pdp/events/detectors/portfolio.py` — `portfolio_stats` digest (reads journal/portfolio services), `position_change`

## 6. Position sync

- [x] 6.1 Create `src/pdp/events/positions.py` — `PositionSync` background loop running every `EVENTS_POSITION_SYNC_SECONDS`
- [x] 6.2 Live mode: `asyncio.to_thread(dhan.get_positions())` with underlying resolution via `UNDERLYING_MAP` + instruments; paper mode: read PostgreSQL `positions` table
- [x] 6.3 Auto-subscribe new legs + underlying spot via `DhanTickerAdapter`; unsubscribe dropped; track `mtm_peak` per position
- [x] 6.4 Graceful failure: retain last known set + `structlog.warn("position_sync_failed")`

## 7. EventService (orchestrator)

- [x] 7.1 Create/replace `src/pdp/events/service.py` — `EventService` holding detectors, monitored positions, dedup state, and `asyncio.Queue` drained by two background workers (store + push)
- [x] 7.2 `on_bar(bar, snapshot)` — sync, no-op when `EVENTS_ENABLED=false`; run spot/indicator + position detectors per timeframe; `queue.put_nowait(event)` (never blocks)
- [x] 7.3 `on_tick(sid, ltp)` — cheap float checks: price_level_cross, otm_distance, mtm_swing, trailing safe-to-exit
- [x] 7.4 `on_chain(underlying, snapshot)` — OI/PCR/GEX/IV detectors; subscribe to `OptionsHub` broadcasts in main.py
- [x] 7.5 `emit(event)` — dedup gate → `EventStore` enqueue → `EventsHub.publish` → `WebPushSender` enqueue if severity ≥ `EVENTS_PUSH_MIN_SEVERITY`
- [x] 7.6 `start()` / `stop()` background-task lifecycle (mirror `PortfolioService`)

## 8. Web Push delivery

- [x] 8.1 Create `push_subscriptions` PostgreSQL model (`endpoint` PK, `p256dh`, `auth`, `created_at`) + Alembic migration
- [x] 8.2 Create `src/pdp/events/push.py` — `WebPushSender.send(event)` via `pywebpush` + VAPID; prune 404/410; non-fatal (log + continue)

## 9. REST + WS routes

- [x] 9.1 Create/replace `src/pdp/events/routes.py` — `GET /api/v1/events` (history, filters: security_id, event_type, severity, limit), `GET /api/v1/events/config`, `GET /api/v1/events/push/vapid-key`, `POST /api/v1/events/push/subscribe`, WebSocket `/ws/events`
- [x] 9.2 Register router + WS in `src/pdp/main.py`

## 10. Wiring (TickRouter, OptionsHub, main.py lifecycle)

- [x] 10.1 In `main.py` lifespan: instantiate `EventsHub`, `EventStore`, `WebPushSender`, `EventService`, `PositionSync`; `await event_service.start()`; stop both in shutdown
- [x] 10.2 Add `event_service` parameter to `TickRouter`; call `event_service.on_bar(bar, snapshot)` after `IndicatorEngine.on_bar` and `event_service.on_tick(sid, ltp)` in tick handler — both guarded by `EVENTS_ENABLED`
- [x] 10.3 Subscribe `EventService.on_chain` to `OptionsHub` broadcasts in `main.py`

## 11. Wire high-priority event types in existing services

- [x] 11.1 `ORDER_FILL`: wire `event_service.on_order_fill` via `orders_hub.register_fill_callback` in `main.py`
- [x] 11.2 `SL_HIT` / `TARGET_HIT`: stubs added to `EventType`; deep per-strategy instrumentation deferred
- [x] 11.3 `KILL_SWITCH_TRIGGERED`: emit from `_auto_kill` callback in `main.py` after kill switch fires
- [x] 11.4 `MARGIN_WARNING`: `portfolio_service.set_margin_warning_callback` wired in `main.py`; fires at `RISK_SOFT_CAP_PCT` of daily cap
- [x] 11.5 `STRATEGY_SIGNAL`: `strategy_host.set_event_service(event_service)` wired in `main.py`; emits on fill events

## 12. Frontend — event feed components

- [x] 12.1 Create `frontend/src/hooks/useEventsWS.ts` — WebSocket hook for `/ws/events`; prepends events to feed; auto-reconnects; returns `{ events, isConnected, unreadCount }`
- [x] 12.2 Create `frontend/src/components/events/EventCard.tsx` — timestamp (relative IST), lucide icon per type, severity Badge (info=blue / warning=amber / error=red / critical=red+pulse), title, description, action link
- [x] 12.3 Create `frontend/src/components/events/EventFilters.tsx` — multi-select type checkboxes, severity toggle pills, date-range picker; `applyFilters` helper for client-side filtering
- [x] 12.4 Create `frontend/src/components/events/EventFeed.tsx` — reverse-chronological EventCard list + EventFilters + "Load More" pagination from `GET /api/v1/events`
- [x] 12.5 Create `frontend/src/components/events/WebPushManager.tsx` — opt-in button, VAPID key fetch, requestPermission, pushManager.subscribe, POST to backend
- [x] 12.6 Create `frontend/src/components/events/EventConfigView.tsx` — per-event-type toggle switches from `GET /api/v1/events/config`

## 13. Frontend — service worker, route, sidebar badge

- [x] 13.1 Create `frontend/public/sw.js` — service worker: `push` event → `self.registration.showNotification(title, options)` with severity icon
- [x] 13.2 Create `frontend/src/routes/events.tsx` — layout: EventFeed + Tabs for PushSettings and EventConfig; register route in `__root.tsx`
- [x] 13.3 Update `frontend/src/components/Sidebar.tsx` — add Events link under SYSTEM group with `Bell` icon and unread-count badge; badge clears on `/events` visit (update `localStorage events_last_seen`)

## 14. Tests

- [x] 14.1 `tests/indicators/test_period_levels.py` — boundary freeze (week/month), seeding from bars, snapshot exposure
- [x] 14.2 `tests/events/test_detectors_spot.py` — edge-trigger + dedup for EMA cross, PSAR flip, Camarilla touch, price-level cross
- [x] 14.3 `tests/events/test_detectors_position.py` — OTM distance, trailing giveback, momentum reversal, MTM swing
- [x] 14.4 `tests/events/test_detectors_oi.py` — OI buildup, PCR band cross, GEX wall, confluence zone
- [x] 14.5 `tests/events/test_position_sync.py` — Dhan mapping, PG fallback, graceful failure (error retains last set)
- [x] 14.6 `tests/events/test_service.py` — dedup/cooldown state machine, push severity gating, `EVENTS_ENABLED=false` no-op
- [x] 14.7 Run `task test` — all pass; `task lint` — no errors; `task typecheck` — no errors

## 15. Final verification

- [x] 15.1 `task dev` with `EVENTS_ENABLED=true` — verify p99 tick→WS ≤ 50ms (no hot-path regression)
- [x] 15.2 Navigate to `/events` — live events appear on bar close; filter by severity works; unread badge counts correctly
- [x] 15.3 Trigger a paper order fill — verify `ORDER_FILL` event appears in feed with correct payload
- [x] 15.4 Trigger kill switch — verify `KILL_SWITCH_TRIGGERED` event appears with critical severity and pulse badge
- [x] 15.5 Enable push notifications → trigger event above WARNING severity → browser push notification fires
- [x] 15.6 Update `src/pdp/events/CLAUDE.md` with module index; update root `CLAUDE.md` events/ row
