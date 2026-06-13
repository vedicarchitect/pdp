## 1. Settings and database migration

- [ ] 1.1 Add `EXECUTION_MODE: Literal["auto", "semi-auto", "manual"] = "auto"` and `AUTO_APPROVE_TIMEOUT_SECONDS: int = 30` to `src/pdp/settings.py`
- [ ] 1.2 Add `PENDING_APPROVAL = "PENDING_APPROVAL"` to `OrderStatus` enum in `src/pdp/orders/models.py`
- [ ] 1.3 Generate Alembic migration to add `'PENDING_APPROVAL'` to the `orderstatus` PostgreSQL enum: `alembic revision --autogenerate -m "add pending_approval order status"`
- [ ] 1.4 Review generated migration file — verify it uses `ALTER TYPE orderstatus ADD VALUE 'PENDING_APPROVAL'` (PostgreSQL enum extension)

## 2. OrderRouter refactor

- [ ] 2.1 Extract broker-dispatch logic from `place_order` into a private `_dispatch_to_broker(self, session, order)` method in `src/pdp/orders/router.py`
- [ ] 2.2 In `place_order`, branch on `self._settings.EXECUTION_MODE`: if `"auto"`, use existing flow (status=`OPEN`, call `_dispatch_to_broker`); otherwise set status=`PENDING_APPROVAL`, persist, and return without dispatching
- [ ] 2.3 Add cancellation support for `PENDING_APPROVAL` status in the `DELETE /api/v1/orders/{id}` handler (currently only cancels `OPEN` orders)

## 3. ApprovalService

- [ ] 3.1 Create `src/pdp/orders/approval.py` with `ApprovalService` class
- [ ] 3.2 Implement `approve(session, order_id) -> Order` — validate status is `PENDING_APPROVAL`, call `_dispatch_to_broker`, update status to `OPEN`, log `order_approved`
- [ ] 3.3 Implement `reject(session, order_id, reason="operator_rejected") -> Order` — validate status is `PENDING_APPROVAL`, set status to `REJECTED`, set `reject_reason`, log `order_rejected`
- [ ] 3.4 Implement `async run()` loop — every 5 seconds, if `EXECUTION_MODE=="semi-auto"`, query orders where `status="PENDING_APPROVAL"` and `placed_at < now() - timeout`; call `approve()` on each; log `order_auto_approved`
- [ ] 3.5 On `run()` startup, query and log all pre-existing `PENDING_APPROVAL` orders at `warning` level (`pending_approvals_on_startup`)

## 4. Approval REST endpoints

- [ ] 4.1 Create `src/pdp/orders/approval_routes.py` with FastAPI router under `/api/v1/approvals`
- [ ] 4.2 Implement `GET /api/v1/approvals` — query `orders WHERE status='PENDING_APPROVAL' ORDER BY placed_at DESC`; return list with computed `estimated_cost_inr = qty × (price or 0)`
- [ ] 4.3 Implement `POST /api/v1/approvals/{id}/approve` — call `ApprovalService.approve()`; return updated order; 404 if not found or not pending
- [ ] 4.4 Implement `POST /api/v1/approvals/{id}/reject` — call `ApprovalService.reject()`; return updated order; 404 if not found or not pending
- [ ] 4.5 Register `approval_routes.router` in `src/pdp/main.py`
- [ ] 4.6 Start `ApprovalService` background task in `main.py` lifespan (alongside existing `OptionsChainPoller` pattern)

## 5. Tests

- [ ] 5.1 Create `tests/orders/test_approval.py`
- [ ] 5.2 Test `auto` mode: `place_order` returns status `OPEN` and calls `_dispatch_to_broker`
- [ ] 5.3 Test `semi-auto` mode: `place_order` returns status `PENDING_APPROVAL` and does NOT call `_dispatch_to_broker`
- [ ] 5.4 Test `approve()`: transitions `PENDING_APPROVAL` → `OPEN` and calls `_dispatch_to_broker`
- [ ] 5.5 Test `reject()`: transitions `PENDING_APPROVAL` → `REJECTED` with correct `reject_reason`
- [ ] 5.6 Test `approve()` on non-pending order raises `404` / appropriate error
- [ ] 5.7 Run `pytest tests/orders/ -v` — all pass

## 6. Frontend — route and panel

- [ ] 6.1 Create `frontend/src/routes/approvals.tsx` — `createFileRoute('/approvals')` with `ApprovalsPanel` component
- [ ] 6.2 Create `frontend/src/components/approvals/ApprovalsPanel.tsx` — TanStack Query fetch of `/api/v1/approvals` with `refetchInterval: 5_000`
- [ ] 6.3 Render a table with columns: Time (IST), Security ID, Side, Qty, Type, Price, Strategy, and Approve/Reject action buttons
- [ ] 6.4 Approve button: `POST /api/v1/approvals/{id}/approve`, invalidate query on success, show toast/brief feedback
- [ ] 6.5 Reject button: `POST /api/v1/approvals/{id}/reject`, invalidate query on success
- [ ] 6.6 Empty state: show "No pending orders" message when list is empty

## 7. Frontend — sidebar badge and mode indicator

- [ ] 7.1 Add "Approvals" nav link to `frontend/src/components/Sidebar.tsx` (icon: `ClipboardCheck` from lucide-react)
- [ ] 7.2 Fetch `/api/v1/approvals` in Sidebar (shared TanStack Query cache, no extra request); show numeric badge on link when count > 0; hide badge when count = 0
- [ ] 7.3 Extend `ModeBanner` (or add a secondary badge) to show `SEMI-AUTO` / `MANUAL` label when `EXECUTION_MODE` is non-auto — read from a new `GET /api/v1/approvals/mode` endpoint that returns `{"execution_mode": "semi-auto", "auto_approve_timeout_seconds": 30}`
- [ ] 7.4 Add `GET /api/v1/approvals/mode` endpoint to `approval_routes.py` returning execution mode settings

## 8. Integration check

- [ ] 8.1 Run `alembic upgrade head` against the local dev database — migration applies cleanly
- [ ] 8.2 Start the API with `EXECUTION_MODE=semi-auto`; place an order via `POST /api/v1/orders`; verify it appears in `GET /api/v1/approvals`
- [ ] 8.3 Approve via `POST /api/v1/approvals/{id}/approve`; verify order status becomes `OPEN` in `GET /api/v1/orders/{id}`
- [ ] 8.4 Start frontend dev server; navigate to `/approvals`; verify panel renders and buttons work end-to-end
