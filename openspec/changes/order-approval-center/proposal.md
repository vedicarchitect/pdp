## Why

PDP is paper-first by design, but the path to live trading requires a safety layer that doesn't exist yet: a human review step between "strategy fires a signal" and "order reaches the broker". Without this, the first live session carries the full risk of any strategy bug being instantly executed at real money. An approval center lets the operator inspect every order intent, approve the expected ones, and reject surprises — without touching strategy code and without permanently blocking automation.

## What Changes

- New `EXECUTION_MODE` setting: `"auto"` (current behavior, default), `"semi-auto"` (orders queue pending, auto-approve after timeout), `"manual"` (orders queue pending, never auto-approve).
- New `OrderStatus.PENDING_APPROVAL` state inserted before `OPEN` in the order state machine.
- `OrderRouter.place_order` checks `EXECUTION_MODE`: in non-auto mode it persists orders as `PENDING_APPROVAL` instead of `OPEN` and does not hand them to the broker immediately.
- New `ApprovalService` background task: holds the pending queue in PostgreSQL (via order status), auto-promotes timed-out orders in `semi-auto` mode, exposes `approve()` and `reject()` methods.
- New REST endpoints under `/api/v1/approvals`: list pending, approve, reject.
- New frontend route `/approvals` with an `ApprovalsPanel` component — live-polling table of pending orders with Approve / Reject buttons per row and a mode badge.
- `ModeBanner` or `Sidebar` gains a pending-count badge that lights up when approvals are waiting.

## Capabilities

### New Capabilities
- `order-approval-center`: Pending approval queue, execution mode setting, approve/reject REST endpoints, and frontend approvals panel.

### Modified Capabilities
- `order-execution`: `OrderStatus` gains `PENDING_APPROVAL` state; `OrderRouter.place_order` branches on `EXECUTION_MODE`; order state machine updated: `NEW → PENDING_APPROVAL → OPEN → (FILLED | CANCELLED | REJECTED)` in non-auto mode.

## Impact

- `src/pdp/settings.py` — add `EXECUTION_MODE: Literal["auto", "semi-auto", "manual"] = "auto"` and `AUTO_APPROVE_TIMEOUT_SECONDS: int = 30`.
- `src/pdp/orders/models.py` — add `PENDING_APPROVAL = "PENDING_APPROVAL"` to `OrderStatus`.
- `src/pdp/orders/router.py` — branch in `place_order` based on `EXECUTION_MODE`.
- New `src/pdp/orders/approval.py` — `ApprovalService` with `approve()`, `reject()`, background timeout-promotion loop.
- New `src/pdp/orders/approval_routes.py` — FastAPI router under `/api/v1/approvals`.
- `src/pdp/main.py` — start `ApprovalService` background task.
- `frontend/src/routes/approvals.tsx` — new route.
- `frontend/src/components/approvals/ApprovalsPanel.tsx` — new component.
- `frontend/src/components/Sidebar.tsx` — pending-count badge on Approvals link.
- `frontend/src/routes/__root.tsx` — register `/approvals` route.
- Tests: `tests/orders/test_approval.py`.
- No new external dependencies; no new database tables (uses existing `orders` table with new status value).
