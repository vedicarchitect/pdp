# Design — api-openapi-schema-completeness (GOVERNANCE 5-phase)

Follows `openspec/GOVERNANCE.md`. Response-surface only; no business logic, no datastore change.

## 1. Architectural Scope & Multi-Service Map

- **Target files (FastAPI):** per-module `schemas.py` (new/extended) under `orders/`,
  `portfolio/`, `risk/`, `journal/`, `positional/`, `broker_sync/`, `backtest/`, `events/`,
  `alerts/`, `strategy/`, `market/`; plus `response_model=`/`status_code=` edits on those routers;
  a shared `pdp/schemas.py` for the generic `Page[T]` wrapper.
- **Flutter/Dart:** none required now (JSON unchanged; schema merely typed). Optional future:
  regenerate models from `/openapi.json`.
- **Terraform / Docker / AWS:** none.
- **Dependencies:** none added. `fastapi` + `pydantic` already generate OpenAPI.
- **Service interactions:** unchanged — `client → route (response_model) → FastAPI serializes`.

**Checklist:** files listed ✅ · no infra ✅ · no new deps ✅

## 2. Phase 1 — Dual-Write & Schema Contracts

### Generic page wrapper + example response models
```python
# pdp/schemas.py
T = TypeVar("T")
class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int | None = None

# orders/schemas.py
class OrderOut(BaseModel):
    id: int
    security_id: str
    side: Literal["BUY", "SELL"]
    qty: int
    status: str
    avg_price: float | None = None
    strategy_id: str
    placed_at: datetime

# portfolio/schemas.py
class PositionOut(BaseModel):
    strategy_id: str
    security_id: str
    net_qty: int
    avg_price: float
    unrealized_pnl: float
    realized_pnl: float
```
```python
# usage
@router.get("/orders", response_model=Page[OrderOut])
async def list_orders(page: PaginationParams = Depends(), ...): ...
@router.post("/orders", response_model=OrderOut, status_code=201)
async def place_order(req: OrderRequest, _: None = Depends(require_auth)): ...
```

### PostgreSQL / MongoDB / OpenSearch / Redis
No schema change anywhere — response models are a serialization contract over data that already
exists. **No migrations.**

**Checklist:** response models explicit ✅ · no DDL/BSON/index change ✅ · Redis unchanged ✅

## 3. Phase 2 — Transactional Core Logic & Guard Clauses

No transactional logic changes. The only guard is a **build-time contract**: the OpenAPI schema
must declare a response model for each mutating route. Error boundaries are inherited from change
#1 (401/400/422/409/503). Status-code hygiene: `POST` create → `201`, `POST` action (kill,
reset) → `200`/`202`, `DELETE` → `204`.

**Checklist:** status-code map ✅ · error boundaries inherited from #1 ✅

## 4. Phase 3 — Cross-Service Validation Tests

`backend/tests/test_openapi_contract.py`:
```python
def test_openapi_documents_all_mutating_routes():
    schema = app.openapi()
    MUT = {"post", "put", "patch", "delete"}
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method in MUT:
                resp = op["responses"]
                ok = next((c for c in resp if c.startswith("2")), None)
                assert ok, f"{method} {path} has no 2xx response"
                content = resp[ok].get("content", {})
                assert content, f"{method} {path} 2xx has no response schema"
```
- Happy: every mutating route has a typed 2xx schema.
- Edge: a list endpoint's schema is a `Page` object; a `DELETE` documents `204`.
- Failure: a deliberately-untyped handler (fixture) trips the assertion.

**Checklist:** contract test ✅ · happy + edge + failure ✅ · runs in CI (`task test`) ✅

## 5. Phase 4 — State, Event I/O & Deployment Handlers

- **Event I/O:** none.
- **Terraform / Docker/Compose:** none. `/docs` and `/redoc` are already exposed on the API
  service; no port/env change.
- **Health checks:** unchanged.

**Checklist:** no event/infra change ✅ · docs endpoints already served ✅
