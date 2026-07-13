# events/ — Live Event Publisher

Position-aware realtime monitoring. Watches **manual Dhan positions** + the underlying
market via the universal `IndicatorEngine` + option analytics, runs a detector library,
de-duplicates, persists to MongoDB, and fans out to WebSocket + Web Push. **Alerts-only —
never places orders.** Spec: `openspec/changes/event-publisher/`.

## Files

| File | Role |
|------|------|
| `models.py` | `Event`, `EventType` (57 types), `Severity`, `MonitoredPosition` |
| `models_db.py` | `PushSubscription` ORM (PG, migration `0011`) |
| `config.py` | JSON-string `EVENTS_*` parsers + `EventConfig.from_settings()` |
| `service.py` | `EventService` — orchestrator: `on_bar`/`on_tick`/`on_chain`, dedup gate, background workers |
| `positions.py` | `PositionSync` — polls Dhan `get_positions()` (PG fallback), auto-subscribes legs+underlying |
| `detectors/base.py` | `BarContext`, `PrevStore` (cross/flip edges), `RollingZ` (z-score) |
| `detectors/levels.py` | price-level cross, level-proximity, confluence-zone |
| `detectors/trend.py` | EMA cross, price⇄EMA, SuperTrend flip, PSAR, MACD, Elder, Elliott, RSI, ML flip |
| `detectors/range_volume.py` | level break (PDH/PDL/PWH/PWL/PMH/PML), custom range, volume spike, VP S/R, gap |
| `detectors/oi_greeks.py` | OI wall, OI buildup, OI vol-spike, PCR, GEX, max-pain, IV, delta-neutral, breakeven |
| `detectors/position.py` | MTM swing, OTM distance, safe-to-exit (trail+momentum), leg-stop, junction |
| `detectors/portfolio.py` | `PORTFOLIO_STATS` digest (# trades, premium, P&L, max profit/loss) |
| `store.py` | `EventStore` — Mongo `events` writer + `list_events()` |
| `hub.py` | `EventsHub` — `/ws/events` fan-out (bounded queue, backfill) |
| `push.py` | `WebPushSender` — VAPID Web Push + subscription pruning |
| `routes.py` | `/api/v1/events` (history/config/push) + `/ws/events` |

## Flow

```
TickRouter._handle ─► IndicatorEngine.on_bar ─► EventService.on_bar(bar)   [sync, bar-close]
                   └─► EventService.on_tick(sid, ltp)                       [O(1) LTP cache]
PositionSync (poll get_positions 30s) ──► monitored set + auto-subscribe
OptionsHub.broadcast ──► EventService.on_chain(underlying, doc)
            detectors → emit() [dedup+cooldown] → EventsHub + EventStore(queue) + WebPush(queue)
```

## Rules

- **No blocking I/O on `on_bar`/`on_tick`** (tick-router hot path). Mongo + push are queued to
  background workers. `on_bar` runs only on bar close; `on_tick` only caches LTP.
- Detectors are **edge-triggered** (hold previous state in `PrevStore`) and do **no I/O**.
- De-dup/cooldown is centralised in `EventService.emit` keyed by `Event.dedup_key`.
- New indicators belong in `indicators/` (rule #4) — detectors **consume** snapshots, never compute.
- Settings via `get_settings()` → `EventConfig.from_settings()`. Timeframes default
  `5m/15m/30m/1H/1D` (`EVENTS_SPOT_TIMEFRAMES`).
- Coexists with `alerts/` (user-defined single-security threshold rules); does not replace it.
- **One event type names exactly one condition** — never reuse a type for two unrelated causes.
  A dashboard/alert rule counting a type must be able to trust what it means. This is why
  `LEG_TYPE_CONTRADICTED` (a leg's tracked kind contradicts the broker's net_qty sign on close —
  a data-corruption alarm) is separate from `POSITION_SIZE_CAPPED` (`_reserve_leg_lots` genuinely
  refusing/clipping a fresh open at the per-sid lot cap — a risk-limit doing its job), even though
  both originate in `directional_strangle.py`. See `tests/strategies/test_event_taxonomy.py`.
- **Readiness taxonomy** (`pdp/strategy/readiness.py` + `DirectionalStrangle.check_readiness()`):
  a strategy's per-component gate (Reconciliation, Broker Sync, Indicators, Chain, Bias) composed
  into one `ok`/`degraded`/`blocked` state, re-evaluated every bar. `blocked` refuses new entries
  and emits `STRATEGY_READINESS_CHANGED` once on transition (existing legs still manage stops/rolls/
  square-off — the gate only blocks new entries, see `on_bar`). Exposed at
  `GET /api/v1/strangle/readiness`.

## Adding a detector

1. Add an `EventType` to `models.py`.
2. Implement in the relevant `detectors/*.py` class; return `Event`s, set a stable `dedup_key`.
3. Call it from the right `EventService` hook (`on_bar` / tick check / `on_chain`).
4. Add a test under `tests/events/`.
