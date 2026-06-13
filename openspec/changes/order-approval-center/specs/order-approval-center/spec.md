## ADDED Requirements

### Requirement: Execution mode setting
The system SHALL support an `EXECUTION_MODE` environment variable with values `"auto"` (default), `"semi-auto"`, and `"manual"`. In `"auto"` mode the system behavior SHALL be identical to the current paper/live flow with no approval step. In `"semi-auto"` mode new orders enter a pending queue and are automatically promoted after `AUTO_APPROVE_TIMEOUT_SECONDS` (default 30) if not acted on. In `"manual"` mode new orders enter the pending queue and are never auto-promoted.

#### Scenario: Auto mode behaves as today
- **WHEN** `EXECUTION_MODE=auto` (or unset) and an order is placed
- **THEN** the order is created with status `OPEN` and dispatched to the broker immediately, with no approval step

#### Scenario: Semi-auto mode creates pending order
- **WHEN** `EXECUTION_MODE=semi-auto` and a strategy places an order
- **THEN** the order is persisted with status `PENDING_APPROVAL` and NOT dispatched to the broker

#### Scenario: Manual mode creates pending order
- **WHEN** `EXECUTION_MODE=manual` and a strategy places an order
- **THEN** the order is persisted with status `PENDING_APPROVAL` and NOT dispatched to the broker

---

### Requirement: ApprovalService auto-promotion in semi-auto mode
In `semi-auto` mode the system SHALL automatically promote `PENDING_APPROVAL` orders to `OPEN` and dispatch them to the broker once `AUTO_APPROVE_TIMEOUT_SECONDS` have elapsed since `placed_at`. Each auto-promotion SHALL be logged at `info` level with `event="order_auto_approved"`, `order_id`, and `strategy_id`. In `manual` mode no auto-promotion SHALL occur.

#### Scenario: Order auto-promoted after timeout
- **WHEN** `EXECUTION_MODE=semi-auto`, `AUTO_APPROVE_TIMEOUT_SECONDS=30`, and an order has been pending for 31 seconds
- **THEN** the order status transitions to `OPEN`, it is dispatched to the broker, and `order_auto_approved` is logged

#### Scenario: Manual mode never auto-promotes
- **WHEN** `EXECUTION_MODE=manual` and a pending order has been waiting for 120 seconds
- **THEN** the order remains in `PENDING_APPROVAL` status

---

### Requirement: Approval REST endpoints
The system SHALL expose:
- `GET /api/v1/approvals` — returns all orders with status `PENDING_APPROVAL`, newest first, with fields: `order_id`, `security_id`, `side`, `qty`, `order_type`, `price`, `strategy_id`, `placed_at`, `estimated_cost_inr`.
- `POST /api/v1/approvals/{id}/approve` — transitions order to `OPEN` and dispatches to broker; returns updated order; returns HTTP 404 if not found or not pending.
- `POST /api/v1/approvals/{id}/reject` — transitions order to `REJECTED` with `reject_reason="operator_rejected"`; returns updated order; returns HTTP 404 if not found or not pending.

#### Scenario: List pending orders
- **WHEN** three orders are in `PENDING_APPROVAL` status and `GET /api/v1/approvals` is called
- **THEN** HTTP 200 is returned with a JSON array of three order objects, newest first

#### Scenario: Approve a pending order
- **WHEN** `POST /api/v1/approvals/{id}/approve` is called on a pending order
- **THEN** HTTP 200 is returned, the order status is `OPEN`, and the order is dispatched to the broker

#### Scenario: Reject a pending order
- **WHEN** `POST /api/v1/approvals/{id}/reject` is called on a pending order
- **THEN** HTTP 200 is returned, the order status is `REJECTED`, and `reject_reason = "operator_rejected"`

#### Scenario: Approve non-pending order returns 404
- **WHEN** `POST /api/v1/approvals/{id}/approve` is called on an order with status `OPEN` or `FILLED`
- **THEN** HTTP 404 is returned

---

### Requirement: Approvals frontend panel
The system SHALL provide a `/approvals` frontend route displaying a table of pending orders with columns: Time, Symbol, Side, Lots, Type, Price, Strategy, and action buttons Approve (green) and Reject (red). The panel SHALL poll `GET /api/v1/approvals` every 5 seconds. The Sidebar SHALL show a numeric badge on the Approvals link when the pending count is greater than zero.

#### Scenario: Pending order appears in panel
- **WHEN** a strategy places an order in semi-auto mode and the user views `/approvals`
- **THEN** the order appears in the table within 5 seconds

#### Scenario: Approve button dispatches order and removes row
- **WHEN** the user clicks Approve on a pending order row
- **THEN** a `POST /api/v1/approvals/{id}/approve` request is made, and the row disappears from the table on the next poll

#### Scenario: Sidebar badge shows pending count
- **WHEN** two orders are pending
- **THEN** the Sidebar Approvals link shows a badge with "2"

#### Scenario: Empty panel shows no-orders message
- **WHEN** no orders are pending
- **THEN** the panel shows "No pending orders" and the Sidebar badge is hidden
