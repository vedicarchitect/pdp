## Context

`OrderRouter.place_order` currently calls `select_broker()` to pick paper or dhan, then immediately creates an `OPEN` order and hands it to the broker engine (`PaperBroker` or `DhanBroker`). There is no interception point and no `PENDING_APPROVAL` state in the `OrderStatus` enum. The existing state machine is `NEW → OPEN → FILLED | CANCELLED | REJECTED`.

The `orders` table is in PostgreSQL. The `ApprovalService` can use the same table — a `PENDING_APPROVAL` row is just an order that hasn't been handed to the broker yet. No Redis or separate queue needed; PostgreSQL is the source of truth.

The frontend polls the REST API (TanStack Query); no WebSocket push is needed for approvals since the latency requirement is human-scale (seconds), not sub-second.

## Goals / Non-Goals

**Goals:**
- Gate broker dispatch behind an explicit approval step in `semi-auto` and `manual` modes.
- Auto-promote pending orders after `AUTO_APPROVE_TIMEOUT_SECONDS` in `semi-auto` mode.
- Provide a frontend panel to inspect and act on pending orders.
- Keep `auto` mode behavior identical to today — zero regression.

**Non-Goals:**
- Partial approval (approve some legs but not others in a strategy signal).
- Modifying the order parameters at approval time (approve-as-is or reject, no edit).
- Per-strategy execution mode (one global mode for now).
- Approval history / audit log beyond what is already in the `orders` table.

## Decisions

### D1: `PENDING_APPROVAL` as a new `OrderStatus` value, not a separate table

The `orders` table already carries everything needed: `security_id`, `side`, `qty`, `price`, `strategy_id`, `placed_at`. Adding a new status is the minimal-schema change. The `ApprovalService` queries `WHERE status = 'PENDING_APPROVAL'` to find the queue.

**Alternative considered:** Separate `pending_approvals` table with a FK to `orders`. Rejected — adds join complexity and a second migration for no additional expressiveness.

### D2: `ApprovalService` runs as a FastAPI `lifespan` background task

The service needs to run a periodic loop (check for timed-out `PENDING_APPROVAL` orders and promote them in `semi-auto` mode). Using `asyncio.create_task` inside the existing `lifespan` context manager (same pattern as `OptionsChainPoller` and `StrategyHost`) keeps the lifecycle consistent.

```python
class ApprovalService:
    async def run(self) -> None:
        while True:
            if self._settings.EXECUTION_MODE == "semi-auto":
                await self._promote_timed_out()
            await asyncio.sleep(5)  # poll every 5s

    async def approve(self, session, order_id: UUID) -> Order: ...
    async def reject(self, session, order_id: UUID, reason: str) -> Order: ...
    async def _promote_timed_out(self) -> None: ...
```

### D3: `OrderRouter.place_order` — branching on `EXECUTION_MODE`

```python
if self._settings.EXECUTION_MODE == "auto":
    status = OrderStatus.OPEN if not reject_reason else OrderStatus.REJECTED
    # ... existing flow, hand to broker immediately
else:
    status = OrderStatus.PENDING_APPROVAL if not reject_reason else OrderStatus.REJECTED
    # persist and return WITHOUT handing to broker
    # ApprovalService.approve() will hand to broker later
```

The broker-dispatch logic (currently inline in `place_order`) is extracted to a `_dispatch_to_broker(session, order)` private method so both `place_order` (auto path) and `ApprovalService.approve()` (manual/semi-auto path) can call it.

### D4: Auto-promote uses `placed_at` + `AUTO_APPROVE_TIMEOUT_SECONDS`

```sql
SELECT * FROM orders
WHERE status = 'PENDING_APPROVAL'
  AND placed_at < NOW() - INTERVAL '<timeout> seconds'
```

For each matched order, call `_dispatch_to_broker()` and update status to `OPEN`. Log `order_auto_approved` with `order_id` and `strategy_id`.

### D5: REST endpoints — three, all under `/api/v1/approvals`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/approvals` | List all `PENDING_APPROVAL` orders, newest first |
| `POST` | `/api/v1/approvals/{id}/approve` | Approve a pending order → dispatch to broker |
| `POST` | `/api/v1/approvals/{id}/reject` | Reject → set `REJECTED` + `reject_reason = "operator_rejected"` |

Response body for approve/reject: the updated `Order` object. 404 if order not found or not in `PENDING_APPROVAL` status.

### D6: Frontend polls `/api/v1/approvals` every 5 seconds

TanStack Query `refetchInterval: 5_000` — fast enough that operators see new orders promptly. The Sidebar badge fetches the same endpoint and shows the count only when `> 0`.

### D7: Mode badge in the existing `ModeBanner`

`ModeBanner` already shows `PAPER` / `LIVE` mode. Extend it to also show `SEMI-AUTO` or `MANUAL` when `EXECUTION_MODE` is non-auto. Fetch from a new `GET /api/v1/settings/execution-mode` endpoint (or extend existing settings endpoint if one exists).

## Risks / Trade-offs

- [Order hangs in PENDING_APPROVAL during crash] If the API process crashes while orders are pending, they stay in `PENDING_APPROVAL` on restart. → On `ApprovalService.run()` startup, log all pre-existing `PENDING_APPROVAL` orders at `warn` level so the operator knows. In `semi-auto` mode the timeout loop will promote them.
- [Strategy sees no fill event during pending] The strategy's `on_fill` won't fire until approval. For a chained strategy (uses the fill to open a hedge), this could cause inconsistency. → Document this limitation. The approval center is intended for order-by-order validation, not for high-frequency chained strategies.
- [Clock skew on timeout] `placed_at` is UTC; the comparison uses `NOW()` in Postgres which is also UTC. → No issue.

## Migration Plan

1. Alembic migration: add `'PENDING_APPROVAL'` to the `orderstatus` PostgreSQL enum.
2. Add `EXECUTION_MODE` and `AUTO_APPROVE_TIMEOUT_SECONDS` to `settings.py`.
3. Add `ApprovalService` and approval routes.
4. Update `OrderRouter` to branch on mode.
5. Wire `ApprovalService` into `main.py` lifespan.
6. Build frontend panel.
7. Rollback: set `EXECUTION_MODE=auto` to revert to current behavior with no code change.

## Open Questions

- None — the design is fully determined by existing patterns in the codebase.
