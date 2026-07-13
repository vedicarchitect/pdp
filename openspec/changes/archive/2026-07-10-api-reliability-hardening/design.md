# Design — api-reliability-hardening (GOVERNANCE 5-phase)

Follows `openspec/GOVERNANCE.md`. This is a backend-only hardening change; no Flutter/Terraform
surface except the Dart models that already consume the affected endpoints (unchanged shapes).

## 1. Architectural Scope & Multi-Service Map

- **Target files (FastAPI):** `backend/pdp/deps.py` (new), `orders/routes.py`,
  `orders/router.py`, `orders/paper.py`, `orders/dhan_broker.py`, `journal/routes.py`,
  `journal/service.py`, `alerts/evaluator.py`, `risk/service.py`, `risk/routes.py`,
  `portfolio/service.py`, `portfolio/routes.py`, `strategy/routes.py`, `broker_sync/routes.py`,
  `backtest/routes.py`, `options/gap_backfill.py`, `market/dhan_ws.py`, `db/session.py`,
  `mongo/client.py`, `settings.py` (new tunables).
- **Flutter/Dart:** none (endpoint response shapes unchanged; only status codes for
  invalid/unauth requests change — the app already handles non-2xx).
- **Terraform / Docker / AWS:** none. New pool tunables are env vars read via `get_settings()`.
- **Dependencies (pinned, already in `backend/pyproject.toml`):** `fastapi`, `sqlalchemy[asyncio]`,
  `asyncpg`, `motor`, `pymongo`, `pydantic`, `pydantic-settings`. No new dependency added.
- **Service interactions:** `API → require_auth (settings) → handler`; `handler → OrderRouter →
  select_broker() → Paper|Dhan broker → PostgreSQL (orders/trades/positions)`; failures on
  money/data paths → `EventService` (see change #4). Pools: `API/engine/ops → PG pool`, `→ Motor pool`.

**Checklist:** all affected files listed ✅ · no infra change ✅ · no new/unpinned deps ✅

## 2. Phase 1 — Dual-Write & Schema Contracts

### FastAPI Pydantic schemas (`deps.py` + per-route)
```python
# deps.py
from fastapi import Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from datetime import date as _date
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_auth(key: str | None = Security(_api_key)) -> None:
    from pdp.settings import get_settings
    expected = get_settings().API_AUTH_KEY
    if not expected or key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

class PaginationParams:
    def __init__(self, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset

def parse_ist_date(date: str | None = None) -> _date:
    if not date:
        from datetime import datetime
        return datetime.now(_IST).date()
    try:
        return _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be ISO-8601 (YYYY-MM-DD)")
```
```python
# orders/routes.py
class OrderRequest(BaseModel):
    security_id: str
    side: Literal["BUY", "SELL"]
    qty: int = Field(gt=0)                    # was: bare int
    product: str
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    price: float | None = Field(default=None, gt=0)
    strategy_id: str

# journal/routes.py
class JournalMetadata(BaseModel):
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
```

### PostgreSQL — no DDL change
Existing constraints already correct: `positions` unique `(strategy_id, security_id,
exchange_segment, product)` (migration 0012); `orders`/`trades` FKs + indices (0005/0015). This
change adds **no migration**; the reversal fix (C1) and idempotency fix (C3/C4) are pure logic.

### MongoDB — no schema change
`paper_journal` document shape unchanged; the fix (C2) is that a metadata edit loads existing
`trades` before `$set`.

### Redis — unchanged
`ltp:<sid>` (EX 5) semantics unchanged; the idempotency fix relies on order status, not Redis.

### Settings (new, with defaults)
```
API_AUTH_KEY: str = ""                 # empty ⇒ auth disabled (dev); set in prod .env → SSM
DB_POOL_RECYCLE_SECONDS: int = 1800
DB_POOL_TIMEOUT_SECONDS: int = 30
MONGO_SOCKET_TIMEOUT_MS: int = 20000
MONGO_CONNECT_TIMEOUT_MS: int = 5000
MONGO_MAX_POOL_SIZE: int = 50
MONGO_MAX_IDLE_TIME_MS: int = 60000
```

**Checklist:** Pydantic constraints ✅ · no DDL/BSON change (logic-only) ✅ · Redis unchanged ✅ ·
settings explicit ✅

## 3. Phase 2 — Transactional Core Logic & Guard Clauses

### Idempotent fill (C3/C4)
```python
async def _fill(self, order: Order, ltp: Decimal, ...) -> None:
    if order.status == OrderStatus.FILLED:      # guard: already booked
        return
    order.status = OrderStatus.FILLED
    ...  # insert Trade, upsert_position — now runs exactly once
```

### Reversal cost basis (C1)
```python
else:  # reducing OR reversing
    reduce_qty = min(abs(qty), abs(old_qty))
    ... book realized on reduce_qty (existing) ...
    if (old_qty > 0) != (new_qty > 0) and new_qty != 0:   # sign flipped through zero
        pos.avg_price = fill_price                          # re-base residual leg
```

### Durable journal metadata (C2)
```python
async def update_metadata(self, day, notes, tags, screenshots):
    if day not in self._trades_by_day and self._mongo is not None:
        doc = await self._mongo["paper_journal"].find_one({"date": day})
        if doc and isinstance(doc.get("trades"), list):
            self._trades_by_day[day] = doc["trades"]     # hydrate before flush
    self._notes_by_day[day] = notes; ...; self._dirty_days.add(day)
```

### Persistent alert lifecycle (C6/C7)
```python
async def _update_alert_state(self, alert, new_status):
    async with self._get_session() as s:
        await update_alert_status(s, alert.id, new_status)   # commit, not detached mutate
        await s.commit()
    if new_status == AlertStatus.RESOLVED:
        self._last_fired.pop(alert.id, None)                 # allow re-arm on re-cross
```

### Error boundaries (matrix)
```python
# 401 — missing/invalid credential (require_auth)
# 400 — malformed date (parse_ist_date)
# 422 — qty<=0 / limit>500 / bad body (Pydantic)
# 409 — order already filled/cancelled on cancel
# 503 — broker offline / DB pool exhausted
```
Money/data-path `except Exception` blocks that currently `log.warning` and swallow SHALL either
re-raise or emit a CRITICAL event (handoff to change #4); teardown/boundary excepts unchanged.

**Checklist:** signatures given ✅ · idempotency key = order status ✅ · error codes mapped ✅

## 4. Phase 3 — Cross-Service Validation Tests

`backend/tests/` (pytest async, `AsyncClient` + mocked broker/DB):
- `test_auth_required` — mutating routes 401 without key, 200/202 with key (≥2 happy + edge).
- `test_order_qty_validation` — `qty=0` → 422, `qty=-75` → 422, `qty=75` → accepted.
- `test_backtest_routes_resolve` — `GET /api/v1/backtests` → 200 (regression for the 422 bug).
- `test_fill_idempotent` — double `_fill` ⇒ one Trade, position moved once.
- `test_position_reversal_costbasis` — `+75@100` then `SELL 150@120` ⇒ realized on 75,
  residual `-75 @ 120`, unrealized 0 at ltp 120.
- `test_journal_metadata_preserves_trades` — edit past-day notes ⇒ stored `trades` intact.
- `test_alert_rearm` — resolve then re-cross ⇒ fires again; restart ⇒ no duplicate.
- Mock payloads: `{success:{qty:75}, edge:{qty:0},{qty:-1},{date:"bad"}, failure:{limit:99999}}`.

**Checklist:** ≥2 happy + 3 edge per fixed endpoint ✅ · mock success/edge/failure ✅ ·
runs under `task test` ✅

## 5. Phase 4 — State, Event I/O & Deployment Handlers

- **Event I/O:** money/data-path failures publish to the events pipeline; the concrete CRITICAL
  event shapes are owned by change #4 (`strategy-critical-data-alerts`). This change only
  ensures the failures are raised, not swallowed.
- **Terraform:** none.
- **Docker/Compose:** none (new settings are plain env vars; add the six keys to
  `backend/.env.example` and `infra/compose/docker-compose.yml` `api` env block with defaults).
- **Health checks:** unchanged here; readiness/liveness coverage is expanded in change #3.

**Checklist:** event handoff noted ✅ · no Terraform ✅ · env vars documented ✅
