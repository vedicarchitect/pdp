## Context

The current `src/pdp/events/` module is a skeleton. It has a basic `EventService` with `emit()` and a type registry, REST/WS routes wired in `main.py`, and VAPID-key support — but only ~4 of 14 planned event types emit actual events, and there is no detector library, no position monitoring loop, and no frontend. The universal `IndicatorEngine` covers 9 indicator families but lacks a `period_levels` family (PWH/PWL/PMH/PML), which detectors need.

This change supersedes the open `event-publisher` in-flight change and delivers the complete event system end-to-end.

## Goals / Non-Goals

**Goals:**
- Full detector library: 30+ detector types across 5 families, edge-triggered, de-duplicated.
- Position-aware monitoring: track manually-held Dhan positions; auto-subscribe legs to tick feed.
- Period levels: add PWH/PWL/PMH/PML to the universal IndicatorEngine.
- Real-time delivery: WebSocket fan-out + Web Push (VAPID) for off-screen notifications.
- Frontend event feed with filtering, push opt-in, and per-event config.

**Non-Goals:**
- Order placement — events are observe-only, never place orders.
- Email/SMS notifications — Web Push only.
- Event aggregation or trend analytics.

## Architecture

### Hot Path (tick → bar close → detectors)

```
TickRouter.on_bar(bar, tf)
  → IndicatorEngine.on_bar(...)       [sync, <1ms]
  → EventService.on_bar(bar, snap)    [sync, enqueue only — no I/O]
       └── for each timeframe in EVENTS_SPOT_TIMEFRAMES:
             run_detectors(snap, tf)  [pure functions, no await]
             if event: queue.put_nowait(event)
  → return                             [hot path exits]

Background workers (asyncio.Task × 2):
  EventStore.write(event)  → MongoDB `events` collection
  EventsHub.publish(event) → WebSocket fan-out
  WebPushSender.send(event) if severity ≥ PUSH_MIN_SEVERITY
```

`on_tick(sid, ltp)` runs on every tick: price-level cross and OTM-distance checks (float comparisons only, no indicators needed).

`on_chain(underlying, chain_snap)` runs on each option-chain refresh: OI/PCR/GEX/IV detectors.

### Detector Protocol

```python
class Detector(Protocol):
    def evaluate(
        self, bar: Bar, snapshot: Snapshot,
        positions: list[MonitoredPosition],
        state: DetectorState,
    ) -> list[Event]: ...
```

Each detector is a pure function. `DetectorState` holds per-key dedup + cooldown state and is mutated by `EventService` after evaluation. CPU budget per detector: <0.1ms on the bar close path.

### De-duplication State Machine

```
key = (security_id, detector_name, level_key)

ARMED → FIRED (on triggering edge)   → emit event
FIRED → COOLDOWN (immediately)        → no repeat for EVENTS_COOLDOWN_SECONDS
COOLDOWN → ARMED (after cooldown)     → ready to fire again
FIRED → ARMED (condition releases before cooldown) → re-arms immediately
```

### Period Levels Family

New `PeriodLevelsTracker` follows the standard family protocol:
```python
def update(high, low, close, volume, bar_time) -> PeriodLevelsState | None
```
Freezes the accumulated period high/low at day/ISO-week/month boundary. Seeded during warmup from MongoDB `market_bars` (last week + last month of daily bars).

Exposed via `IndicatorEngine.get_period_levels(sid, tf)`, `Snapshot.period_levels`, and `IndicatorReader.period_levels(sid, tf)`.

### PositionSync

```
every EVENTS_POSITION_SYNC_SECONDS (default 30s):
  live mode: asyncio.to_thread(dhan.get_positions())
  paper mode: SELECT * FROM positions WHERE net_qty != 0

for each new leg:
  resolve underlying from UNDERLYING_MAP + instruments registry
  DhanTickerAdapter.subscribe(security_id) + subscribe(underlying_spot_id)
  init mtm_peak = avg_price

for each dropped leg:
  DhanTickerAdapter.unsubscribe(security_id)

on error:
  retain last known set
  structlog.warn("position_sync_failed", exc_info=True)
```

### WebSocket Delivery

`EventsHub` mirrors the existing `AlertsHub` pattern:
- One `asyncio.Queue(maxsize=100)` per connected client — drops oldest on full (never blocks publisher).
- On connect: backfill last 50 events from `EventStore`.
- On disconnect: queue removed.

### Web Push

`WebPushSender` uses `pywebpush` with VAPID keys from settings. Subscriptions stored in PostgreSQL `push_subscriptions` table (endpoint PK, p256dh, auth). 404/410 responses from send prune the subscription row.

## Frontend Design

### Event Card

```
┌────────────────────────────────────────────────┐
│ ⚡ [info]  Strategy Signal          2m ago      │
│ SuperTrend SHORT signal · NIFTY · 15m          │
│ SuperTrend(10,2) flipped bearish at 24,750      │
│                                                │
│ ⚠ [warning]  OTM Distance Alert    5m ago      │
│ NIFTY 24000 CE · spot within 95 pts            │
│                                                │
│ 🔴 [critical]  Kill Switch Triggered  1h ago   │
│ Daily loss cap breached. All positions closed. │
└────────────────────────────────────────────────┘
```

Severity badge colours: info=blue, warning=amber, error=red, critical=red + pulse animation.
IST timestamps, relative display ("2m ago"), full ISO on hover.

### Filter Bar

```
[All Types ▼]  [All Severity ▼]  [Today ▼]   🔔 Enable Push
```

Type filter is multi-select (checkboxes). Applied client-side for in-memory WS events; as query params for REST history load.

### Web Push Opt-in Flow

1. Click "Enable Push Notifications"
2. `GET /api/v1/events/push/vapid-key` → VAPID public key
3. `Notification.requestPermission()` → user grants
4. `serviceWorker.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: vapidKey})`
5. `POST /api/v1/events/push/subscribe` with subscription object
6. UI shows "Push enabled ✓"

`frontend/public/sw.js` service worker listens for `push` events and calls `showNotification()`.

### Sidebar Unread Badge

`localStorage.setItem("events_last_seen", Date.now())` on each visit to `/events`. Badge count = number of events with `ts > events_last_seen` received since last visit, tracked in React state via the WS hook.

## Settings Added to `settings.py`

| Setting | Default | Purpose |
|---------|---------|---------|
| `EVENTS_ENABLED` | `false` | Master on/off switch |
| `EVENTS_SPOT_TIMEFRAMES` | `["5m","15m","30m","1H","1D"]` | Which TFs to run detectors on |
| `EVENTS_WATCH_LEVELS` | `{}` | `{security_id: [price, ...]}` custom price levels |
| `EVENTS_OTM_DISTANCE_PTS` | `150` | Points to OTM strike for alert |
| `EVENTS_MTM_SWING_INR` | `2000` | MTM change threshold for swing event |
| `EVENTS_TRAIL_GIVEBACK_PCT` | `30` | % giveback from MTM peak for safe-to-exit |
| `EVENTS_OI_BUILDUP_PCT` | `20` | OI % change threshold for OI buildup event |
| `EVENTS_PCR_BANDS` | `[0.7, 1.3]` | PCR band edges for shift event |
| `EVENTS_GEX_WALL_PTS` | `100` | Proximity to GEX wall for alert |
| `EVENTS_CONFLUENCE_MIN` | `2` | Minimum aligned sources for confluence event |
| `EVENTS_CONFLUENCE_BAND_PTS` | `30` | Band width for confluence clustering |
| `EVENTS_POSITION_SYNC_SECONDS` | `30` | Interval for PositionSync loop |
| `EVENTS_COOLDOWN_SECONDS` | `300` | Per-key cooldown after emission |
| `EVENTS_TTL_DAYS` | `14` | MongoDB event TTL |
| `EVENTS_PUSH_ENABLED` | `false` | Web Push on/off |
| `EVENTS_PUSH_MIN_SEVERITY` | `WARNING` | Minimum severity for push |
| `EVENTS_VAPID_PUBLIC_KEY` | — | VAPID public key |
| `EVENTS_VAPID_PRIVATE_KEY` | — | VAPID private key |
| `EVENTS_VAPID_SUBJECT` | — | VAPID contact email |
| `EVENTS_STATS_INTERVAL_SECONDS` | `300` | Portfolio stats digest interval |

## Risks / Trade-offs

- **Hot path safety**: Detectors are pure functions; all I/O is async-queued. `EventService` always returns from `on_bar` in <5ms. If the queue is full, events are dropped (bounded), never blocking the bar handler.
- **CPU budget per detector**: Detector library runs all families every bar close. With 30+ detectors × 5 timeframes, budget is ~150 evaluations per bar. Each pure-function evaluation should complete in <0.1ms; total: well within the 50ms tick budget.
- **pywebpush dependency**: Small, well-maintained. Delivery failures are non-fatal (logged, retried next event).
- **Period levels warmup**: Requires at least one prior week of daily `market_bars` in MongoDB. Gracefully skips PWH/PWL if less data available.
- **Delta computation**: `DELTA_NEUTRAL_DRIFT` detector needs per-position delta. Source is chain Greeks for option positions; direct delta from chain snapshot. Falls back to ignoring positions with no chain data.

## Open Questions

- **Daily 1D timeframe**: `market/bars.py` needs a 1D aggregator. Seeded from `market_bars` MongoDB during warmup (already exists for backtest). Scope as a minimal BarAggregator extension.
- **Service worker**: `frontend/public/sw.js` must be created if absent. No conflict with existing service workers since none exist in the current frontend build.
