# Design — execution-console-daily-parity (GOVERNANCE 5-phase)

Follows `openspec/GOVERNANCE.md`. Cross-service (strategy engine + orders ledger + broker sync +
Flutter). Depends on change #1 (`upsert_position` C1 fix) and change #4 (`emit_critical` + event
types). Evidence: 2026-07-08 monitor snapshot — SENSEX legs `entry —` with MTM `= -ltp × qty`.

## 1. Architectural Scope & Multi-Service Map

- **Target files (Python):**
  - `strategies/directional_strangle.py` — `_await_fill_avg_px` (never return 0), leg-open path,
    new startup `rehydrate_legs()`, reconcile hook.
  - `orders/paper.py` + `orders/dhan_broker.py` — extract `compute_position_update()` pure helper
    used by `upsert_position` (re-base cost basis on flat-open / reversal).
  - `strategy/trade_ledger.py` — durable source (PG `trades` + Mongo `events`); JSONL fallback.
  - `strategy/routes.py` — `/strangle/trades` reads durable ledger.
  - new `strategy/reconcile.py` — three-way reconciler.
  - `broker_sync/scheduler.py` (+ new `broker_sync/intraday_poller.py`), `service.py`,
    `routes.py` — intraday refresh + `last_synced_at`.
  - `settings.py` — `BROKER_INTRADAY_POLL_SECONDS`, `BROKER_STALE_SECONDS`,
    `RECONCILE_TOLERANCE_LOTS`.
  - `events/models.py` — add `POSITION_RECONCILE_MISMATCH` event type (reuses change #4 plumbing).
- **Flutter/Dart:** `app/lib/` — Live account tab shows `last_synced_at` + stale badge; Execution
  tab shows a reconciliation-mismatch warning banner. No new screen.
- **Dependencies:** none new — reuses `motor`, `sqlalchemy[asyncio]`, existing
  `BrokerAccountClient`, `EventService`.
- **Service interactions:**
```
DirectionalStrangle (in-memory legs) ──rehydrate/reconcile──► PG orders.Position
        │  entry_price (resolved, never 0)                         ▲
        └── emit_critical ──► events (Mongo + WS + Push)           │
BrokerAccountClient ──intraday poll──► broker_sync mirror (PG) ────┘  reconcile
Flutter ◄── /strangle/{legs,monitor,trades}, /broker-sync/{positions,holdings,funds}+last_synced_at
```

**Checklist:** files listed ✅ · infra none/env-tunable ✅ · no new deps ✅ · diagram ✅

## 2. Phase 1 — Dual-Write & Schema Contracts

### Pure position-update helper (Python)
```python
def compute_position_update(old_qty: int, old_avg: Decimal,
                            fill_qty: int, fill_price: Decimal) -> PositionUpdate:
    """Return (new_qty, new_avg, realized_delta). Single source of truth for both
    paper and dhan upsert_position. avg is re-based to fill_price whenever the
    position opens from flat (old_qty == 0) or reverses sign; weighted-average on
    same-sign adds; realized booked on the closed quantity."""
```

### Fill-price resolution (Python)
```python
async def resolve_fill_price(sid: str, ...) -> Decimal | None:
    # broker avg → ltp_cache → chain ltp → last bar close ; None if all cold
```

### Durable ledger source
```
rows = pair_trades( leg_events_from(PG trades ⨝ Mongo events "leg_open"/"leg_close", day, sid) )
# same pair_trades() logic; only the source changes. JSONL only if durable source empty.
```

### Broker-sync read contract (adds one field)
```
GET /api/v1/broker-sync/positions|holdings|funds
  → { ..., "last_synced_at": "<ISO8601 UTC>" }     # new
```

### Redis / Mongo / PostgreSQL / OpenSearch
- **Redis:** reuse `ltp:<sid>`; optional `broker:last_sync` string (EX). No new hot-path key.
- **Mongo:** no new collection — reads existing `events`; `POSITION_RECONCILE_MISMATCH` is a new
  `event_type` value in the existing `events` schema.
- **PostgreSQL:** no DDL — `BrokerSyncRun.finished_at` already gives `last_synced_at`;
  `Position.avg_price` semantics corrected (data-quality, not schema).
- **OpenSearch:** reconcile mismatches log at WARNING via structlog (existing pipeline).

**Checklist:** pure helper contract ✅ · resolve contract ✅ · durable source ✅ · one new event
value, no new DDL/collection ✅ · Redis/OpenSearch noted ✅

## 3. Phase 2 — Transactional Core Logic & Guard Clauses

### Never-zero entry (guard)
```python
avg_px = await self._await_fill_avg_px(sid)          # broker avg, may be 0
if avg_px <= 0:
    avg_px = await resolve_fill_price(sid, ...)       # cache/chain/bar fallbacks
if avg_px is None or avg_px <= 0:
    await self._square_leg(sid)                        # do not record a naked/zero leg
    await self.ctx.emit_critical(EventType.MISSING_LTP, sid=sid, detail="entry unresolved")
    return
```

### Cost-basis re-base (branch-free, unit-tested)
`compute_position_update` is the sole writer of `avg_price`; `upsert_position` calls it and
persists. Old inline branches deleted.

### Leg rehydration idempotency
`rehydrate_legs()` runs once on startup, keyed so a leg already present is not duplicated; a leg in
PG with `net_qty == 0` is skipped.

### Reconcile tolerance + write ownership
Reconciler is **read-only** (no position writes); emits events only. Runs on a timer + after each
fill. Divergence within `RECONCILE_TOLERANCE_LOTS` is ignored.

### Error boundaries
```
missing entry price   → square leg + CRITICAL MISSING_LTP (never store entry 0)
reconcile divergence  → CRITICAL POSITION_RECONCILE_MISMATCH (read-only, no auto-trade)
broker poll failure   → mirror keeps last good snapshot; last_synced_at unchanged; WARNING log
                        (paper/no-creds → silent no-op, never crash)
```

**Checklist:** never-zero guard ✅ · single avg_price writer ✅ · idempotent rehydrate ✅ ·
read-only reconciler ✅ · error boundaries ✅

## 4. Phase 3 — Cross-Service Validation Tests

`backend/tests/strategy/` + `tests/orders/` + `tests/broker_sync/`:
- `test_no_zero_entry_on_cold_cache` — open with cold `ltp:` + unresolved broker avg ⇒ leg squared
  + `MISSING_LTP` emitted, **no** leg stored with `entry_price=0` (happy-path guard).
- `test_mtm_not_phantom` — a leg's MTM is never `-ltp × qty` (regression on the exact SENSEX bug).
- `test_compute_position_update_reopen` — flat→reopen sets `avg_price = fill_price` (edge).
- `test_compute_position_update_reversal` — long→short through zero re-bases `avg_price` + books
  realized on closed qty (edge).
- `test_rehydrate_legs_after_restart` — legs in PG ⇒ reconstructed with correct entry (edge).
- `test_ledger_durable_after_restart` — trades ledger complete from PG+Mongo with the JSONL file
  absent (edge).
- `test_intraday_poll_updates_mirror` — poller refreshes mirror + `last_synced_at` (happy).
- `test_reconcile_emits_on_divergence` — leg with no broker position ⇒ `POSITION_RECONCILE_MISMATCH`
  (edge).
- Flutter: widget test — stale `last_synced_at` ⇒ badge shown; reconcile mismatch ⇒ banner.
- Mock JSON: `{success: resolved fill, edge: cold cache / reversal / restart, failure: broker poll error}`.

**Checklist:** ≥2 happy + ≥3 edge across entry/position/ledger/broker ✅ · Flutter test ✅ ·
mock success/edge/failure ✅

## 5. Phase 4 — State, Event I/O & Deployment Handlers

### Event I/O
```
emit_critical MISSING_LTP                {sid, strategy_id, detail}      (reuses #4)
emit_critical POSITION_RECONCILE_MISMATCH {sid, side, leg_qty, broker_qty, detail}
```
Both flow through the existing `events` pipeline → Mongo `events` (TTL) + `/ws/events` + Web Push.

### State
- `Position.avg_price` corrected in place (data quality) — a one-off reconcile/repair script MAY
  re-base any currently-zero open positions; no migration.
- Broker mirror gains no columns (`last_synced_at` = existing `BrokerSyncRun.finished_at`).

### Deployment
- No Terraform / no new container. Settings: `BROKER_INTRADAY_POLL_SECONDS` (default 30, market
  hours only), `BROKER_STALE_SECONDS` (default 120), `RECONCILE_TOLERANCE_LOTS` (default 0).
- After change #3 (worker split) the intraday poller + reconciler run in the `ops`/`engine`
  process; here they attach to the existing lifespan. Health: reconcile + poll failures are logged,
  never crash the process.

**Checklist:** event shapes ✅ · state/repair-script noted, no migration ✅ · settings + process
placement ✅ · Terraform deferred ✅
