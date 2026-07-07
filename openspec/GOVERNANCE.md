# OpenSpec Proposal Governance

For infrastructure changes, multi-service refactors, and proposals requiring cross-team validation, every feature proposal must adhere to this strict 5-phase structure. This ensures design clarity, testability, and safe implementation across our polyglot stack.

---

## 1. Architectural Scope & Multi-Service Map

Define the boundary of the feature precisely:

- **Target Files:** List every file path affected across Flutter, FastAPI, Terraform, and Docker.
- **Infrastructure Footprint:** Explicitly state if this changes AWS resources, Docker volumes, or local networking.
- **Dependencies:** List exact versions (e.g., `pubspec.yaml`, `requirements.txt`). Do **not** use "latest".
- **Service Interactions:** Which services call which? Draw a box diagram if multiple services are involved.

**Checklist:**
- [ ] All affected files listed (no surprises during implementation)
- [ ] Infrastructure changes (AWS, volumes, networking) called out explicitly
- [ ] Dependency versions pinned (dev, test, prod)

---

## 2. Phase 1: Dual-Write & Schema Contracts

Because we use a polyglot database layer (PostgreSQL ACID + MongoDB time-series + Redis cache), you must provide absolute, explicit data contracts for all target data stores:

### FastAPI Pydantic Schemas
- Explicit types, validation constraints, and field aliases
- Example:
  ```python
  class OrderCreate(BaseModel):
      symbol: str
      side: Literal["BUY", "SELL"]
      quantity: int = Field(gt=0)
      price: float = Field(gt=0) | None = None
  ```

### Flutter / Dart Models
- Complete serialization (`fromJson`, `toJson`) without placeholders
- Example:
  ```dart
  factory Order.fromJson(Map<String, dynamic> json) {
    return Order(
      id: json['id'],
      symbol: json['symbol'],
      side: json['side'],
      quantity: json['quantity'],
    );
  }
  ```

### Storage Target Shapes

**PostgreSQL:** Exact SQL DDL migration scripts
```sql
CREATE TABLE orders (
  id UUID PRIMARY KEY,
  account_id UUID NOT NULL REFERENCES accounts(id),
  instrument_id VARCHAR NOT NULL REFERENCES instruments(id),
  side VARCHAR(4) CHECK (side IN ('BUY', 'SELL')),
  quantity INT NOT NULL CHECK (quantity > 0),
  price DECIMAL(10,2),
  status VARCHAR(20) DEFAULT 'PENDING',
  created_at TIMESTAMP DEFAULT NOW(),
  INDEX idx_account_id (account_id),
  INDEX idx_created_at (created_at)
);
```

**MongoDB:** Exact BSON schema validation
```json
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": ["symbol", "timestamp"],
    "properties": {
      "_id": { "bsonType": "objectId" },
      "symbol": { "bsonType": "string" },
      "timestamp": { "bsonType": "date" },
      "bar": {
        "bsonType": "object",
        "properties": {
          "open": { "bsonType": "double" },
          "high": { "bsonType": "double" },
          "close": { "bsonType": "double" }
        }
      }
    }
  }
}
```

**OpenSearch:** Complete index mapping
```json
{
  "mappings": {
    "properties": {
      "timestamp": { "type": "date" },
      "event_type": { "type": "keyword" },
      "message": { "type": "text" }
    }
  }
}
```

**Redis:** Precise key-naming convention and data structures
```
ltp:{symbol}              → string (LTP price, EX 5s)
bars.{symbol}.{timeframe} → stream (OHLCV bars)
position:{account_id}     → hash (qty, cost, mtm)
```

**Checklist:**
- [ ] Pydantic schemas have validation constraints
- [ ] Dart models have complete serialization
- [ ] PostgreSQL migration includes indices and foreign keys
- [ ] MongoDB schema validation specified
- [ ] OpenSearch mapping defined (type, analyzer)
- [ ] Redis key naming and TTL explicit

---

## 3. Phase 2: Transactional Core Logic & Guard Clauses

Trading features require zero-latency edge case handling. Outline logic using strict patterns:

### Strict Function Signatures
Provide complete signatures for Python/Dart logic:
```python
async def place_order(
    ctx: Context,
    account_id: UUID,
    symbol: str,
    side: Literal["BUY", "SELL"],
    quantity: int,
    price: float | None = None,
) -> Order:
    """
    Atomically place an order. Validates account margin, symbol liquidity, quantity limits.
    Returns Order with status=PENDING.
    """
```

### Race Condition & State Guard Clauses
Explicitly document concurrency control:
```python
# Redis SETNX for idempotency
if await redis.setnx(f"order_request:{order_id}", "processing", ex=10):
    try:
        # Process order
    except Exception:
        await redis.delete(f"order_request:{order_id}")
        raise

# PostgreSQL row lock for multi-leg orders
async with db.begin():
    position = await db.execute(
        select(Position).where(Position.id == pos_id).with_for_update()
    )
    # Update position atomically
```

### Idempotency Rules
Trace how duplicate API requests are caught:
- Use cache key: `{order_id}` → check if already processed
- Use database unique constraint: `UNIQUE(account_id, external_order_id)`
- Use atomic INSERT-OR-UPDATE patterns

### Error Boundaries
Matrix of concrete HTTP/internal error codes:
```python
# 400 Bad Request: validation failure
if quantity <= 0:
    raise HTTPException(400, "quantity must be positive")

# 409 Conflict: state conflict (e.g., position already closed)
if position.quantity == 0:
    raise HTTPException(409, "position already closed")

# 422 Unprocessable: business rule violation
if margin_required > margin_available:
    raise HTTPException(422, "insufficient margin")

# 503 Service Unavailable: broker offline
if dhan_circuit_breaker.is_open():
    raise HTTPException(503, "broker temporarily unavailable")
```

**Checklist:**
- [ ] All functions have type signatures (args, return)
- [ ] Redis/Postgres locking strategy documented
- [ ] Idempotency key specified
- [ ] Error codes mapped to business logic

---

## 4. Phase 3: Cross-Service Validation Tests

You must provide complete, production-ready, un-omitted tests:

### FastAPI / Pytest
Full endpoint integration tests using mocked Redis/DB boundary:
```python
@pytest.mark.asyncio
async def test_place_order_success():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/orders",
            json={"symbol": "NSE_NIFTY50", "side": "BUY", "quantity": 1, "price": 99500}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING"
        assert data["order_id"]

@pytest.mark.asyncio
async def test_place_order_insufficient_margin():
    # Mock: account.margin_available = 100
    response = await client.post(
        "/orders",
        json={"symbol": "NSE_BANKNIFTY", "side": "BUY", "quantity": 100}
    )
    assert response.status_code == 422
    assert "margin" in response.json()["detail"].lower()
```

### Flutter / Dart
Full unit tests for state management:
```dart
test('OrderBloc places order successfully', () async {
  final bloc = OrderBloc(mockOrderService);
  expect(
    bloc.stream,
    emitsInOrder([
      isA<OrderInitial>(),
      isA<OrderLoading>(),
      isA<OrderSuccess>()
          .having((s) => s.order.id, 'id', isNotNull),
    ]),
  );
  
  bloc.add(PlaceOrderEvent(symbol: 'NSE_NIFTY50', side: 'BUY', qty: 1));
});
```

### Mock Data Sets
Exact JSON payloads representing success, edge cases, and failures:
```json
{
  "success": {
    "symbol": "NSE_NIFTY50",
    "side": "BUY",
    "quantity": 1,
    "price": 99500
  },
  "edge_cases": {
    "zero_quantity": { "quantity": 0 },
    "negative_price": { "price": -100 },
    "missing_symbol": { "symbol": null },
    "far_otm_option": { "symbol": "NSE_BANKNIFTY27NOV24C50000" }
  },
  "failures": {
    "margin_insufficient": { "margin_available": 100, "margin_required": 500 },
    "broker_offline": { "dhan_status": "OFFLINE" },
    "circuit_halted": { "symbol_state": "CIRCUIT_HALTED" }
  }
}
```

**Checklist:**
- [ ] FastAPI: ≥2 happy-path + 3 edge-case tests per endpoint
- [ ] Flutter: ≥1 test per bloc/provider state transition
- [ ] Mock data: success, edge case, failure scenarios all present
- [ ] Tests run in CI/CD (pytest + `flutter test`)

---

## 5. Phase 4: State, Event I/O & Deployment Handlers

### I/O Pipelines
Exact shape of events sent to queues or cache layers:
```python
# PublishEvent to Redis pub/sub
class OrderFillEvent(BaseModel):
    order_id: UUID
    symbol: str
    filled_qty: int
    filled_price: float
    timestamp: datetime

# Publish
await redis.publish(f"order.{order_id}", json.dumps(OrderFillEvent(...)))

# Subscribe
async def on_order_fill(event: OrderFillEvent):
    # Update position, MTM P&L
    pass
```

### Terraform Block Changes
Provide exact `.tf` configuration if new AWS resources are needed:
```hcl
resource "aws_rds_cluster" "backtest_read_replica" {
  cluster_identifier           = "pdp-backtest-replica"
  engine                       = "aurora-postgresql"
  engine_version               = "16.1"
  database_name                = "pdp"
  master_username              = "postgres"
  master_password              = var.db_password
  backup_retention_period      = 30
  skip_final_snapshot          = false
  final_snapshot_identifier    = "pdp-snapshot-${timestamp()}"
}
```

### Docker/Compose Bindings
Specific environment variable updates or service block changes:
```yaml
services:
  api:
    environment:
      DATABASE_URL: postgresql+asyncpg://user:pass@postgres:5432/pdp
      REDIS_URL: redis://redis:6379/0
      DHAN_API_KEY: ${DHAN_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
```

**Checklist:**
- [ ] Event shapes (Pydantic or JSON) specified
- [ ] Pub/sub channel names explicit
- [ ] New AWS resources in Terraform (if needed)
- [ ] Environment variables documented in docker-compose.yml
- [ ] Service health checks defined

---

## Summary Checklist

Before submitting a proposal for implementation:

- [ ] **Scope:** Target files + infrastructure footprint + dependencies listed
- [ ] **Schemas:** Pydantic, Dart, PostgreSQL, MongoDB, OpenSearch, Redis all explicit
- [ ] **Logic:** Functions signed, concurrency control documented, error codes mapped
- [ ] **Tests:** Happy path + edge cases + mock data for all services
- [ ] **I/O:** Event shapes + Terraform + docker-compose updates included
- [ ] **Validation:** `openspec validate --strict <id>` passes

Once complete, proceed to implementation with high confidence that edge cases are handled and tests will pass.
