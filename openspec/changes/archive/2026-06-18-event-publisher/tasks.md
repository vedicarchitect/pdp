# Tasks — Live Event Publisher

## 1. Settings & dependencies

- [x] 1.1 Add event settings to `src/pdp/settings.py`: `EVENTS_ENABLED`, `EVENTS_SPOT_TIMEFRAMES`, `EVENTS_WATCH_LEVELS`, `EVENTS_OTM_DISTANCE_PTS`, `EVENTS_MTM_SWING_INR`, `EVENTS_TRAIL_GIVEBACK_PCT`, `EVENTS_OI_BUILDUP_PCT`, `EVENTS_PCR_BANDS`, `EVENTS_GEX_WALL_PTS`, `EVENTS_POSITION_SYNC_SECONDS`, `EVENTS_COOLDOWN_SECONDS`, `EVENTS_TTL_DAYS`, `EVENTS_PUSH_ENABLED`, `EVENTS_PUSH_MIN_SEVERITY`, `EVENTS_VAPID_PUBLIC_KEY`, `EVENTS_VAPID_PRIVATE_KEY`, `EVENTS_VAPID_SUBJECT`
- [x] 1.2 Add `pywebpush` to `pyproject.toml` dependencies; `uv lock`
- [x] 1.3 Add `events` collection (TTL on `ts` = `EVENTS_TTL_DAYS`) init to `src/pdp/mongo/collections.py`

## 2. period_levels indicator family (modifies indicator-suite)

- [x] 2.1 Create `src/pdp/indicators/period_levels.py` — `PeriodLevelsState` (pdh/pdl/pwh/pwl/pmh/pml + session/week/month keys) and `PeriodLevelsTracker.update(...)` + `seed_prior_levels(...)`
- [x] 2.2 Register `period_levels` in `src/pdp/indicators/registry.py`
- [x] 2.3 Add `period_levels: PeriodLevelsState | None = None` to `Snapshot` in `src/pdp/indicators/snapshot.py`
- [x] 2.4 Add `get_period_levels(...)` to `IndicatorEngine` and add `"period_levels"` to `_SUITE_FAMILIES` in `src/pdp/indicators/engine.py`
- [x] 2.5 Seed `period_levels` in `src/pdp/indicators/warmup.py` from MongoDB `market_bars` (trailing week + month aggregation)
- [x] 2.6 Add `period_levels(...)` accessor to `IndicatorReader` in `src/pdp/strategy/context.py`
- [x] 2.7 Tests: `tests/indicators/test_period_levels.py` — boundary freeze (week/month), seeding, snapshot exposure
- [x] 2.8 Update `src/pdp/indicators/CLAUDE.md` family table

## 3. Events module — core (models, store, hub)

- [x] 3.1 Create `src/pdp/events/models.py` — `EventType`, `Severity`, `Event` dataclass (`to_dict`), `MonitoredPosition` dataclass
- [x] 3.2 Create `src/pdp/events/store.py` — `EventStore` async writer to MongoDB `events`; `list_events(filters, limit)` for history
- [x] 3.3 Create `src/pdp/events/hub.py` — `EventsHub` WS fan-out (copy `alerts/ws.py` pattern: bounded queue, drop-oldest, backfill last N)

## 4. Detector library (runs per timeframe in `EVENTS_SPOT_TIMEFRAMES`)

- [x] 4.0 Add `1D` daily-bar aggregation to `src/pdp/market/bars.py` + warmup `_TF_SESSION_BARS`/interval maps so daily detectors work
- [x] 4.1 Create `src/pdp/events/detectors/base.py` — `Detector` protocol, per-key dedup/cooldown state helper, bounded rolling-window helper (volume/OI z-score, divergence)
- [x] 4.2 Create `src/pdp/events/detectors/levels.py` — price_level_cross, level_proximity, confluence_zone (multi-family + OI walls)
- [x] 4.3 Create `src/pdp/events/detectors/trend.py` — ema_crossover (pairs), price_ema_cross, supertrend_flip, psar_flip, macd_cross, elder_impulse, elliott_wave, ml_signal_flip, rsi_extreme
- [x] 4.4 Create `src/pdp/events/detectors/range_volume.py` — level_break (day-H/L + PDH/PDL + PWH/PWL/PMH/PML), custom_range_break, volume_spike, volume_sr, gap_open
- [x] 4.5 Create `src/pdp/events/detectors/oi_greeks.py` — oi_wall, oi_buildup, oi_volume_spike, pcr_shift (reuse `compute_pcr`), gex_wall (reuse `compute_gex`), max_pain_pin (reuse `compute_max_pain`), iv_shift, delta_neutral_drift, breakeven_breach, expiry_countdown
- [x] 4.6 Create `src/pdp/events/detectors/position.py` — mtm_swing, otm_distance, safe_to_exit_trail, safe_to_exit_momentum, leg_stop_proximity, directional_junction
- [x] 4.7 Create `src/pdp/events/detectors/portfolio.py` — portfolio_stats digest (# trades, premium received, P&L, max profit/loss) + position_change, reading journal/portfolio services

## 5. Position sync

- [x] 5.1 Create `src/pdp/events/positions.py` — `PositionSync` background loop; live `get_positions()` (via `asyncio.to_thread`) with PG `positions` fallback; build `MonitoredPosition` set; underlying resolution via `options.dhan_client.UNDERLYING_MAP` + instruments registry
- [x] 5.2 Auto-subscribe new legs + underlying spot via `DhanTickerAdapter`; unsubscribe dropped legs; track `mtm_peak`
- [x] 5.3 Graceful failure: retain last set + log `position_sync_failed`

## 6. EventService (orchestrator)

- [x] 6.1 Create `src/pdp/events/service.py` — `EventService` holding detectors, monitored positions, dedup state, and an `asyncio.Queue` drained by background workers
- [x] 6.2 `on_bar(bar, snapshot)` — sync, no-op when `EVENTS_ENABLED=false`; run spot/indicator + position-momentum detectors; enqueue events
- [x] 6.3 `on_tick(sid, ltp)` — price_level_cross, otm_distance, mtm_swing, trailing safe-to-exit (cheap float comparisons)
- [x] 6.4 `on_chain(underlying, snapshot)` — OI/PCR/GEX detectors; subscribe to `OptionsHub` broadcasts
- [x] 6.5 `emit(event)` — dedup gate → `EventStore` (queue) + `EventsHub.publish` + web-push (queue) when severity ≥ `EVENTS_PUSH_MIN_SEVERITY`
- [x] 6.6 `start()` / `stop()` background-task lifecycle (mirror `PortfolioService`)

## 7. Web Push delivery

- [x] 7.1 Create `push_subscriptions` PG model (`endpoint` PK, `p256dh`, `auth`, `created_at`) + Alembic migration
- [x] 7.2 Create `src/pdp/events/push.py` — `WebPushSender.send(event)` via `pywebpush` + VAPID; prune 404/410 subscriptions
- [x] 7.3 Subscription CRUD helpers (create, list, delete by endpoint)

## 8. REST + WS routes

- [x] 8.1 Create `src/pdp/events/routes.py` — `GET /api/v1/events` (history, filters), `GET /api/v1/events/config`, `GET /api/v1/events/push/vapid-key`, `POST /api/v1/events/push/subscribe`, `WS /ws/events`
- [x] 8.2 Register router + WS in `src/pdp/main.py`

## 9. Wiring (main.py + router)

- [x] 9.1 Add `event_service` param to `TickRouter`; call `event_service.on_bar(bar, snapshot)` after `IndicatorEngine.on_bar` and `event_service.on_tick(sid, ltp)` in `_handle` (guarded, non-blocking)
- [x] 9.2 In `main.py` lifespan: instantiate `EventsHub`, `EventStore`, `WebPushSender`, `EventService`, `PositionSync`; `await event_service.start()`; pass into `TickRouter`; subscribe `EventService.on_chain` to `OptionsHub`
- [x] 9.3 Stop `EventService` + `PositionSync` in lifespan shutdown

## 10. Frontend

- [x] 10.1 `frontend/src/routes/events.tsx` — event feed page, register route in `__root.tsx`
- [x] 10.2 `frontend/src/components/events/EventFeed.tsx` + `EventCard.tsx` — `/ws/events` subscription, severity styling, IST timestamps, type/severity filters
- [x] 10.3 `frontend/public/sw.js` service worker (`push` → `showNotification`) + push-enrol hook (`useEventPush`) calling `/api/v1/events/push/vapid-key` + `/subscribe`
- [x] 10.4 Sidebar link to `/events` with unread-count badge

## 11. Tests & validation

- [x] 11.1 `tests/events/test_detectors_spot.py` — edge-trigger + dedup for EMA cross, PSAR flip, Camarilla, price level
- [x] 11.2 `tests/events/test_detectors_position.py` — OTM distance, trailing giveback, momentum reversal, MTM swing
- [x] 11.3 `tests/events/test_detectors_oi.py` — OI buildup, PCR band cross, GEX wall
- [x] 11.4 `tests/events/test_position_sync.py` — Dhan mapping + PG fallback + graceful failure
- [x] 11.5 `tests/events/test_service.py` — dedup/cooldown, push severity gating, disabled no-op
- [x] 11.6 Run `task test`, `task lint`, `task typecheck`
- [x] 11.7 `task openspec:validate -- event-publisher --strict`

## 12. Docs

- [x] 12.1 Add `src/pdp/events/CLAUDE.md` (module index)
- [x] 12.2 Update root `CLAUDE.md` module index + `src/CLAUDE.md` module map with `events/`
