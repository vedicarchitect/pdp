## Why

The `src/pdp/events/` module is a skeleton: ~4 of 14 planned event types are wired, there is no position-monitoring loop, no indicator/OI detector library, and zero frontend. The user wants a consolidated, real-time event feed that covers the full spectrum of platform activity — strategy signals, order fills, risk events, OI/IV shifts, confluence zones, P&L digests, and safe-to-exit cues — delivered both in-app and via browser push notifications.

This proposal supersedes the open in-flight change `event-publisher`, absorbing its full backend scope alongside the frontend.

## What Changes

### Backend — Event Publisher

- **`period_levels` indicator family**: New family in the universal `IndicatorEngine` providing previous-day (PDH/PDL), previous-week (PWH/PWL), and previous-month (PMH/PML) levels. Seeded from MongoDB `market_bars` during warmup. Required by the detector library for level-break events.

- **`EventService` core** (`src/pdp/events/service.py`): Continuously-running orchestrator. `on_bar(bar, snapshot)` is called by `TickRouter` after `IndicatorEngine.on_bar` — runs the spot/indicator detector library per configured timeframe (`EVENTS_SPOT_TIMEFRAMES`, default `["5m","15m","30m","1H","1D"]`), enqueues results; never blocks the hot path. `on_tick(sid, ltp)` handles cheap price-level and OTM-distance checks on every tick. `on_chain(underlying, snapshot)` runs OI/PCR/GEX detectors on each option-chain refresh.

- **Detector library** (`src/pdp/events/detectors/`):
  - *Levels & confluence*: price-level cross, level-proximity, **confluence-zone** (fires when ≥N sources — EMAs, VWAP, Camarilla, Fibonacci, FVG edges, OI walls, period levels — cluster within a price band).
  - *Trend/momentum*: EMA crossovers (9/20, 9/50, 20/50), price⇄EMA cross, SuperTrend(10,2) flip, Parabolic SAR flip, MACD cross, Elder-impulse change, Elliott-wave label change, ML-signal flip, RSI extreme/divergence.
  - *Range/breakout/volume*: day-H/L, PDH/PDL, PWH/PWL/PMH/PML breaks, custom strangle-range break, volume spike (futures z-score), volume-profile S/R rejection, gap-open at session start.
  - *OI/Greeks*: OI wall S/R + rejection, OI build-up/unwind, OI volume spike, PCR-band cross, GEX-wall proximity, max-pain pin/shift, IV spike/crush, portfolio delta-neutral drift, breakeven breach, expiry countdown. Reuses `compute_pcr`, `compute_gex`, `compute_max_pain` from `options/analytics.py`.
  - *Position/P&L*: MTM swing, OTM-distance approach, safe-to-exit (trailing giveback), safe-to-exit (momentum reversal), leg-stop proximity, directional-junction alert.
  - *Portfolio digest*: periodic `PORTFOLIO_STATS` event from journal/portfolio services (trade count, premium received, realized + unrealized P&L, max profit, max loss).

- **`PositionSync`** (`src/pdp/events/positions.py`): Background loop (every `EVENTS_POSITION_SYNC_SECONDS`, default 30). In live mode reads Dhan `get_positions()`; in paper mode falls back to PostgreSQL `positions` table. Auto-subscribes new legs + underlying spot to the tick feed; unsubscribes closed legs. Graceful failure retains last known set.

- **Event de-duplication + cooldown**: Per `(security_id, detector, level-key)` state machine — fires once on edge, clears when condition releases, blocked for `EVENTS_COOLDOWN_SECONDS` (default 300) from last emission.

- **Persistence**: Every emitted event written to MongoDB `events` collection (TTL = `EVENTS_TTL_DAYS`).

- **Delivery channels**: `EventsHub` WebSocket (`/ws/events`, bounded per-client queue, backfill on connect) + Web Push (VAPID, events at or above `EVENTS_PUSH_MIN_SEVERITY`).

- **REST endpoints** (`GET /api/v1/events`, `GET /api/v1/events/config`, `GET /api/v1/events/push/vapid-key`, `POST /api/v1/events/push/subscribe`).

### Frontend — Event Feed UI

- **`/events` route**: Reverse-chronological live feed — subscribes to `/ws/events`, loads history from `GET /api/v1/events`. Filter by event type and severity. Each event card shows IST timestamp (relative), lucide icon, severity Badge (info/warning/error/critical-pulsing), title, description, optional action link.

- **Web Push opt-in**: "Enable Push Notifications" button → fetches VAPID key → `Notification.requestPermission()` → `pushManager.subscribe()` → `POST /api/v1/events/push/subscribe`. Shows current opt-in state.

- **Per-event config**: Toggles from `GET /api/v1/events/config` — choose which types generate push notifications.

- **Sidebar unread badge**: Counts events received since last `/events` visit (tracked via `localStorage` timestamp).

## Capabilities

### New Capabilities
- `event-publisher`: Full detector library, position sync, de-duplication, MongoDB persistence, WebSocket + Web Push delivery.
- `event-feed-ui`: Frontend event feed with live streaming, filtering, push opt-in, per-event config, unread badge.

### Modified Capabilities
- `events`: Expanded event type wiring (order fill, SL hit, target hit, margin warning, strategy signal, kill-switch) + new REST/WS routes.
- `indicator-suite`: Adds `period_levels` family (PDH/PDL/PWH/PWL/PMH/PML) to the universal engine.

## Impact

**Backend (new):**
- `src/pdp/indicators/period_levels.py` — NEW
- `src/pdp/indicators/registry.py` — MODIFIED (register period_levels)
- `src/pdp/indicators/snapshot.py` — MODIFIED (add `period_levels` field)
- `src/pdp/indicators/engine.py` — MODIFIED (wire period_levels family)
- `src/pdp/indicators/warmup.py` — MODIFIED (seed period_levels from market_bars)
- `src/pdp/strategy/context.py` — MODIFIED (IndicatorReader.period_levels accessor)
- `src/pdp/market/bars.py` — MODIFIED (add 1D daily bar aggregation)
- `src/pdp/events/models.py` — NEW (EventType, Severity, Event, MonitoredPosition)
- `src/pdp/events/store.py` — NEW (MongoDB EventStore)
- `src/pdp/events/hub.py` — NEW (EventsHub WebSocket fan-out)
- `src/pdp/events/push.py` — NEW (WebPushSender + pywebpush)
- `src/pdp/events/positions.py` — NEW (PositionSync background loop)
- `src/pdp/events/service.py` — NEW/REPLACED (EventService orchestrator)
- `src/pdp/events/detectors/base.py` — NEW (Detector protocol, dedup/cooldown helper)
- `src/pdp/events/detectors/levels.py` — NEW
- `src/pdp/events/detectors/trend.py` — NEW
- `src/pdp/events/detectors/range_volume.py` — NEW
- `src/pdp/events/detectors/oi_greeks.py` — NEW
- `src/pdp/events/detectors/position.py` — NEW
- `src/pdp/events/detectors/portfolio.py` — NEW
- `src/pdp/events/routes.py` — NEW/REPLACED (REST + WS endpoints)
- `src/pdp/settings.py` — MODIFIED (all EVENTS_* settings)
- `src/pdp/main.py` — MODIFIED (start EventService, PositionSync, EventsHub; register router/WS)
- `src/pdp/market/router.py` — MODIFIED (call event_service.on_bar + on_tick)
- `alembic/versions/xxx_add_push_subscriptions.py` — NEW
- `tests/events/test_detectors_spot.py` — NEW
- `tests/events/test_detectors_position.py` — NEW
- `tests/events/test_detectors_oi.py` — NEW
- `tests/events/test_position_sync.py` — NEW
- `tests/events/test_service.py` — NEW
- `tests/indicators/test_period_levels.py` — NEW

**Frontend (new):**
- `frontend/src/routes/events.tsx` — NEW
- `frontend/src/components/events/EventFeed.tsx` — NEW
- `frontend/src/components/events/EventCard.tsx` — NEW
- `frontend/src/components/events/EventFilters.tsx` — NEW
- `frontend/src/components/events/PushSettings.tsx` — NEW
- `frontend/src/components/events/EventConfig.tsx` — NEW
- `frontend/src/hooks/useEventsWS.ts` — NEW
- `frontend/public/sw.js` — NEW (Web Push service worker)
- `frontend/src/components/Sidebar.tsx` — MODIFIED (Events link + unread badge)

**New external dependency:** `pywebpush` (Web Push delivery via VAPID)
