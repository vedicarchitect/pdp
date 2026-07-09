# Design — strategy-critical-data-alerts (GOVERNANCE 5-phase)

Follows `openspec/GOVERNANCE.md`. Builds entirely on the existing `events/` pipeline.

## 1. Architectural Scope & Multi-Service Map

- **Target files (FastAPI):** `events/models.py` (new `EventType`s), `events/service.py`
  (`emit_critical`), `strategy/context.py` (`ctx.emit_critical`), `strategies/directional_strangle.py`
  (naked-hedge/ORB/VIX guards), `indicators/warmup.py` + `strategy/host.py` (disarm-until-seeded),
  `market/router.py` / feed watchdog (`FEED_STALE`), plus the money/data-path `except` blocks.
- **Flutter/Dart:** `app/lib/features/events/` — add the six new types to the event enum + an
  icon/severity mapping. No new screen (existing `/ws/events` feed renders them).
- **Terraform / Docker / AWS:** none.
- **Dependencies:** none added. Uses `structlog`, existing `events/` module, `pywebpush` (already
  present for Web Push).
- **Service interactions:** `strategy/warmup/feed → ctx.emit_critical → EventService.emit (dedup)
  → EventsHub (/ws/events) + EventStore (Mongo events) + WebPushSender`.

**Checklist:** files listed ✅ · Flutter enum touch noted ✅ · no infra/new deps ✅

## 2. Phase 1 — Dual-Write & Schema Contracts

### Pydantic / dataclass (Python)
No new persisted schema — reuses the existing `Event` dataclass (`events/models.py`) and its
`to_mongo()`. New enum members only:
```python
class EventType(StrEnum):
    ...
    WARMUP_INCOMPLETE = "WARMUP_INCOMPLETE"
    MISSING_LTP = "MISSING_LTP"
    NAKED_POSITION = "NAKED_POSITION"
    FEED_STALE = "FEED_STALE"
    INDICATOR_UNSEEDED = "INDICATOR_UNSEEDED"
    EXCEPTION_CRITICAL = "EXCEPTION_CRITICAL"
```
Payloads are the existing free-form `payload: dict[str, Any]`; documented shapes:
```python
NAKED_POSITION     payload = {"strategy_id","short_sids":[...],"reason":"hedge_unpriced"}
INDICATOR_UNSEEDED payload = {"strategy_id","indicator":"ORB","expected_window":"09:15-09:30","seen_from":"11:45"}
WARMUP_INCOMPLETE  payload = {"security_id","timeframe","indicator":"EMA200","have_bars":N,"need_bars":M}
FEED_STALE         payload = {"last_tick_ts","stale_seconds":S}
EXCEPTION_CRITICAL payload = {"where":"module.func","exc":"..."}
```

### Dart model
```dart
enum LiveEventType { ..., warmupIncomplete, missingLtp, nakedPosition, feedStale,
                     indicatorUnseeded, exceptionCritical, unknown }
LiveEventType eventTypeFromJson(String s) => _map[s] ?? LiveEventType.unknown;
```

### MongoDB
Existing `events` collection + TTL index (`_ensure_events`). No new collection/index — the new
types are just new `event_type` values (already a `keyword`-style field). **No migration.**

### Redis / OpenSearch
Unchanged. (Events already ship to OpenSearch via the structlog pipeline; the CRITICAL severity
makes them queryable there for free.)

**Checklist:** enum members ✅ · Dart enum ✅ · no new Mongo index (reuse) ✅ · Redis/OS unchanged ✅

## 3. Phase 2 — Transactional Core Logic & Guard Clauses

### Reusable emit path
```python
# events/service.py
def emit_critical(self, event_type: EventType, security_id: str, title: str,
                  message: str, payload: dict[str, Any] | None = None,
                  dedup_key: str | None = None) -> None:
    ev = Event(event_type=event_type, severity=Severity.CRITICAL, security_id=security_id,
               title=title, message=message, payload=payload or {},
               dedup_key=dedup_key or f"{event_type.value}:{security_id}")
    self.emit(ev)   # existing dedup/cooldown + hub + store + push
```
```python
# strategy/context.py — thin, single-responsibility passthrough
def emit_critical(self, event_type, security_id, title, message, payload=None):
    if self._event_service is not None:
        self._event_service.emit_critical(event_type, security_id, title, message, payload)
```

### Naked-hedge guard (directional_strangle)
```python
h_sid = self._pick_hedge()          # existing scan
if h_sid is None:                    # every wing unpriced
    await self._await_first_tick(candidates, timeout=HEDGE_PRICE_WAIT_S)
    h_sid = self._pick_hedge()
if h_sid is None:
    await self._square_short(short_legs)          # do not hold naked
    self.ctx.emit_critical(EventType.NAKED_POSITION, self._sid, "Naked short averted",
                           "hedge unpriced after wait", {"strategy_id": self.id, ...})
    return
```

### Unseeded-ORB guard
```python
if not self._orb_seeded_from_open():   # first 15m bar seen != 09:15-09:30
    self.ctx.emit_critical(EventType.INDICATOR_UNSEEDED, self._sid, "ORB unseeded", ...)
    orb_high = orb_low = None          # exclude ORB vote rather than vote off a bogus range
```

### Disarm-until-seeded
```python
# strategy/host.py before arming
if not engine.is_warm(sid, tfs, min_bars=WARMUP_MIN_BARS):
    self.ctx.emit_critical(EventType.WARMUP_INCOMPLETE, sid, "Warmup incomplete", ...)
    keep_disarmed()
```

### Error boundaries
```python
# 503 — feed stale (FEED_STALE emitted by watchdog, halt already present)
# CRITICAL event — naked position / unseeded indicator / warmup incomplete / swallowed money error
# hot path: emit is O(1) enqueue (no blocking) — safe on on_bar/on_tick per events/CLAUDE.md
```
Idempotency: `dedup_key` (per condition) prevents alert storms; the guard actions
(square/disarm) are themselves idempotent.

**Checklist:** signatures ✅ · dedup key = idempotency ✅ · no blocking on hot path ✅ · error map ✅

## 4. Phase 3 — Cross-Service Validation Tests

`backend/tests/events/` + `tests/strategies/`:
- `test_emit_critical_fans_out` — publishes to hub + store + push; second identical within
  cooldown is suppressed (happy + edge).
- `test_naked_hedge_squares_and_alerts` — cold `ltp:` for all wings ⇒ short squared +
  `NAKED_POSITION` emitted (not naked).
- `test_orb_unseeded_excluded` — restart with first bar at 11:45 ⇒ `INDICATOR_UNSEEDED` + ORB
  vote excluded.
- `test_warmup_incomplete_disarms` — engine short of `WARMUP_MIN_BARS` ⇒ strategy stays
  disarmed + `WARMUP_INCOMPLETE`.
- `test_feed_stale_event` — watchdog trip ⇒ `FEED_STALE` published.
- `test_vix_gate_uses_5m` — gate reads 5m candle series + 09:15 baseline (parity vs backtest).
- Flutter: `app/test/` bloc test that a `NAKED_POSITION` JSON maps to the CRITICAL styling.
- Mock payloads: `{success:{event_type:"NAKED_POSITION",severity:"CRITICAL"},
  edge:{unknown_type}, failure:{missing severity}}`.

**Checklist:** ≥2 happy + 3 edge across the new events ✅ · Flutter bloc test ✅ · mock JSON ✅

## 5. Phase 4 — State, Event I/O & Deployment Handlers

- **Event I/O:** pub/sub + WS shape is the existing `Event.to_dict()`; the only delta is the six
  new `event_type` string values. Web Push honours `EVENTS_PUSH_MIN_SEVERITY` (CRITICAL always
  passes).
- **Terraform:** none.
- **Docker/Compose:** none (no new service/env). Optional new tunables
  (`HEDGE_PRICE_WAIT_S`, `WARMUP_MIN_BARS`) added to `backend/.env.example` with defaults.
- **Health checks:** unchanged.

**Checklist:** event shape delta = enum values only ✅ · no Terraform/compose change ✅ ·
optional tunables documented ✅
