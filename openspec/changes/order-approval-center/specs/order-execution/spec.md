## ADDED Requirements

### Requirement: PENDING_APPROVAL order status
The system SHALL include `PENDING_APPROVAL` as a valid `OrderStatus` value. The extended state machine SHALL be: `PENDING_APPROVAL → OPEN → (FILLED | CANCELLED | REJECTED)` when `EXECUTION_MODE` is non-auto, and the existing `OPEN → (FILLED | CANCELLED | REJECTED)` when `EXECUTION_MODE` is `"auto"`. Cancellation SHALL be possible from both `PENDING_APPROVAL` and `OPEN` states.

#### Scenario: PENDING_APPROVAL status persisted for non-auto mode
- **WHEN** `EXECUTION_MODE=semi-auto` and an order passes lot-size validation
- **THEN** the order is persisted with `status = "PENDING_APPROVAL"` and is not handed to the broker

#### Scenario: Cancel a PENDING_APPROVAL order
- **WHEN** `DELETE /api/v1/orders/{id}` is called on an order with status `PENDING_APPROVAL`
- **THEN** HTTP 200 is returned, status transitions to `CANCELLED`, and `cancelled_at` is set

#### Scenario: Broker dispatch on approval
- **WHEN** `ApprovalService.approve(order_id)` is called on a `PENDING_APPROVAL` order
- **THEN** the order status transitions to `OPEN` and the broker engine receives the order via `_dispatch_to_broker()`

## MODIFIED Requirements

### Requirement: Order placement endpoint
The system SHALL expose `POST /api/v1/orders` accepting `{client_order_id, security_id, exchange_segment, side, qty, order_type, price?, trigger_price?, product, strategy_id?}` and persisting a new order row. In `EXECUTION_MODE=auto` the initial status SHALL be `OPEN` and the order SHALL be dispatched to the broker immediately. In `EXECUTION_MODE=semi-auto` or `EXECUTION_MODE=manual` the initial status SHALL be `PENDING_APPROVAL` and the order SHALL NOT be dispatched to the broker.

#### Scenario: Successful placement in auto mode
- **WHEN** `POST /api/v1/orders` is called with a valid MARKET order body in `EXECUTION_MODE=auto`
- **THEN** the response is HTTP 201 with the created order, status `OPEN`, broker `paper`
- **AND** the response header `X-Trade-Mode: PAPER` is present

#### Scenario: Successful placement in semi-auto mode
- **WHEN** `POST /api/v1/orders` is called with a valid MARKET order body in `EXECUTION_MODE=semi-auto`
- **THEN** the response is HTTP 201 with the created order, status `PENDING_APPROVAL`
- **AND** the order is NOT filled by the paper broker until approved

#### Scenario: Idempotent placement
- **WHEN** the same `client_order_id` is submitted twice
- **THEN** the second response returns the original order with HTTP 200 (not duplicated)
