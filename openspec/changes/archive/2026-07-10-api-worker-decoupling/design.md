# Design — api-worker-decoupling (GOVERNANCE 5-phase)

Follows `openspec/GOVERNANCE.md`. This is the multi-service refactor; the full 5-phase treatment
applies. Satisfies the ratified `repo-architecture` cloud-readiness requirement and feeds the
stubbed `cloud-deploy-aws`.

## 1. Architectural Scope & Multi-Service Map

- **Target files (FastAPI/Python):** `backend/pdp/main.py` (lifespan → group selection), new
  `backend/pdp/runtime/groups.py` (group objects) + `runtime/entrypoints.py` (`pdp-api`,
  `pdp-engine`, `pdp-ops`), `market/router.py` + `market/ws.py` (Redis→WS bridge),
  `orders/command_channel.py` (new — Stream producer/consumer), `orders/router.py`,
  `risk/service.py` (kill as command), `indicators/*` + `portfolio/service.py` (snapshot publish),
  `db/session.py` + `mongo/client.py` (per-process pool sizing), `settings.py` (process role +
  pool sizes), `pyproject.toml` (console-script entrypoints).
- **Infra:** `infra/compose/docker-compose.yml` — add `engine` + `ops` services (same image,
  `command:` differs). No new managed AWS resource here (deferred to `cloud-deploy-aws`).
- **Flutter/Dart:** `app/lib/` — handle the "feed offline"/stale-snapshot indicator + `503` on
  manual order when engine down. No new screen.
- **Dependencies (already present, pinned in `backend/pyproject.toml`):** `redis` (Streams +
  pub/sub), `fastapi`, `uvicorn`, `motor`, `sqlalchemy[asyncio]`, `asyncpg`. No new dependency.
- **Service interactions (box diagram):**
```
Flutter ──HTTP/WS──► pdp-api ──Redis Stream (orders)──► pdp-engine ──► Dhan broker
   ▲                    │  ▲                                 │
   │   /ws/market       │  └── SUBSCRIBE tick.* / XREAD bars.*  (Redis→WS bridge)
   │   /ws/events   ◄───┘                                    │  writes: PG (orders/trades/positions)
                        └── reads: PG ledger, Redis snapshots (indicators:*, position:*)
pdp-ops ──► intel/news scrape, account-sync + scrip-refresh schedulers, chain poller,
            event publisher, job runner (ML train / backfill)  ──► PG/Mongo/Redis
all three ──► infra group: PG pool, Mongo pool, Redis, OpenSearch
```

**Checklist:** all files listed ✅ · infra (compose services) called out ✅ · deps pinned/no new ✅ ·
service diagram ✅

## 2. Phase 1 — Dual-Write & Schema Contracts

### Group protocol (Python)
```python
class StartupGroup(Protocol):
    name: str
    async def start(self, app_state: AppState) -> None: ...
    async def stop(self) -> None: ...

GROUPS_BY_ROLE = {
    "api":    [InfraGroup, WebGroup],
    "engine": [InfraGroup, FeedEngineGroup],
    "ops":    [InfraGroup, OpsGroup, JobRunnerGroup],
}
```

### Order command — Redis Stream (Phase-1 contract)
```
Stream key:        orders.commands
Consumer group:    engine
Idempotency key:   cmd_id (uuid4, client-supplied)  → Redis SETNX cmd:done:<cmd_id> EX 86400
Ack/result stream: orders.results
```
```python
class OrderCommand(BaseModel):        # produced by API
    cmd_id: str
    kind: Literal["place", "cancel", "kill"]
    order: OrderRequest | None = None  # reuses change #1's validated model
    cancel_order_id: int | None = None
    requester: str
    ts: datetime

class OrderResult(BaseModel):         # written by engine
    cmd_id: str
    status: Literal["placed", "cancelled", "rejected", "killed"]
    order_id: int | None = None
    detail: str | None = None
```

### Redis snapshot keys (engine → API)
```
indicators:{sid}:{tf}     → hash  (ema/st/psar/rsi/... ; updated on bar close)      EX 900
position:{strategy}:{sid} → hash  (net_qty, avg_price, unrealized, ltp_stale)       EX 30
engine:status             → string ("warming" | "ready" | "halted")                 EX 15
tick.{sid}                → pub/sub (existing)          bars.{sid}.{tf} → stream (existing)
```

### PostgreSQL / MongoDB
No new tables/collections. Durable state (orders/trades/positions, journal, events) already lives
in PG/Mongo; this change only changes **which process writes** them (engine for fills, ops for
events) and adds `SELECT … FOR UPDATE` on the position write if both engine and portfolio-MTM can
write it (P2). Per-process pool sizing is settings, not DDL.

### OpenSearch
Unchanged (each process ships structlog to the same pipeline; `process_role` added as a log field).

**Checklist:** group protocol ✅ · Stream + idempotency key ✅ · snapshot keys + TTL ✅ ·
no new DDL/BSON ✅ · OpenSearch field noted ✅

## 3. Phase 2 — Transactional Core Logic & Guard Clauses

### Idempotent command consumption (engine)
```python
async for msg in stream_reader("orders.commands", group="engine", consumer=name):
    cmd = OrderCommand.model_validate_json(msg.data)
    if not await redis.set(f"cmd:done:{cmd.cmd_id}", "1", nx=True, ex=86400):
        await ack(msg); continue                     # already processed
    try:
        result = await self._execute(cmd)            # single margin + kill gate → broker
        await redis.xadd("orders.results", result.model_dump())
        await ack(msg)
    except Exception as exc:
        await redis.delete(f"cmd:done:{cmd.cmd_id}") # allow safe retry
        raise
```

### Position write ownership (P2)
```python
async with db.begin():
    pos = (await db.execute(select(Position)
             .where(Position.strategy_id==sid, ...).with_for_update())).scalar_one_or_none()
    ...  # engine (fills) and MTM loop serialize on the row lock
```

### API-side enqueue with bounded wait
```python
# 503 when no engine consumer / result not seen in time
if await engine_status() != "ready" and cmd.kind == "place":
    raise HTTPException(503, "engine unavailable")
await redis.xadd("orders.commands", cmd.model_dump())
result = await await_result(cmd.cmd_id, timeout=ORDER_ACK_TIMEOUT_S)  # 503 on timeout
```

### Error boundaries
```
400/422 — invalid order (change #1 validation, before enqueue)
409     — cancel of an already-filled/cancelled order
503     — engine not ready / ack timeout / DB pool exhausted
group failure — logged + degraded, never process crash (composable groups)
```

**Checklist:** consumer-group idempotency (SETNX) ✅ · row lock for shared position write ✅ ·
error codes mapped ✅

## 4. Phase 3 — Cross-Service Validation Tests

`backend/tests/runtime/` + `tests/orders/`:
- `test_api_boots_without_engine` — `pdp-api` role starts, `/healthz` 200, `/docs` served, no
  Dhan creds.
- `test_group_failure_isolated` — a group whose `start()` raises leaves the process up + other
  groups running.
- `test_order_command_roundtrip` — API enqueues → fake engine consumer places → API gets
  `placed` result (happy).
- `test_command_idempotent_on_restart` — re-deliver same `cmd_id` ⇒ one broker placement (edge).
- `test_order_503_when_engine_down` — no consumer ⇒ `503` (edge).
- `test_ws_bridge_delivers_tick` — publish `tick.<sid>` ⇒ subscribed `/ws/market` client receives
  it (bridge, not in-process).
- `test_indicator_snapshot_read` — engine writes `indicators:<sid>:<tf>` ⇒ API read endpoint
  returns it.
- Flutter: bloc test that engine-down → stale banner + manual-order button disabled/`503` handled.
- Mock JSON: `{success: OrderCommand/OrderResult, edge: duplicate cmd_id, failure: engine-down}`.

**Checklist:** ≥2 happy + 3 edge across boot/command/bridge ✅ · Flutter degradation test ✅ ·
mock success/edge/failure ✅

## 5. Phase 4 — State, Event I/O & Deployment Handlers

### Redis I/O shapes
```
XADD orders.commands  {cmd_id, kind, order{...}, requester, ts}
XADD orders.results   {cmd_id, status, order_id, detail}
PUBLISH tick.<sid>    (existing)      XADD bars.<sid>.<tf> (existing)
HSET indicators:<sid>:<tf> ...        HSET position:<strategy>:<sid> ...
SET  engine:status "ready"|"warming"|"halted"
```

### Docker/Compose (`infra/compose/docker-compose.yml`)
```yaml
services:
  api:
    image: pdp:latest
    command: ["pdp-api"]
    environment: { PDP_ROLE: api, DATABASE_URL: ..., REDIS_URL: ..., MONGO_URI: ... }
    ports: ["8000:8000"]
    depends_on: { postgres: {condition: service_healthy}, redis: {condition: service_started} }
    healthcheck: { test: ["CMD","curl","-f","http://localhost:8000/readyz"], interval: 15s }
  engine:
    image: pdp:latest
    command: ["pdp-engine"]
    environment: { PDP_ROLE: engine, DHAN_CLIENT_ID: ${DHAN_CLIENT_ID}, DHAN_ACCESS_TOKEN: ${DHAN_ACCESS_TOKEN}, ... }
    depends_on: { redis: {condition: service_started}, postgres: {condition: service_healthy} }
  ops:
    image: pdp:latest
    command: ["pdp-ops"]
    environment: { PDP_ROLE: ops, INTEL_ENABLED: "true", ... }
    depends_on: { redis: {condition: service_started} }
```
Console scripts in `pyproject.toml`: `pdp-api`, `pdp-engine`, `pdp-ops` → `pdp.runtime.entrypoints:*`.

### Terraform
None in this change. The 3-service topology + health checks here are the direct input to
`cloud-deploy-aws` (ECS/Fargate task defs, one per role).

### Health checks
`/healthz` (liveness, always-200) unchanged; `/readyz` becomes per-role (api: infra+web; engine:
infra+feed; ops: infra+ops). Compose healthchecks target `/readyz`.

**Checklist:** Redis stream/pubsub/snapshot shapes ✅ · compose 3 services + env + healthcheck ✅ ·
Terraform deferred to cloud-deploy-aws ✅ · console-script entrypoints ✅
