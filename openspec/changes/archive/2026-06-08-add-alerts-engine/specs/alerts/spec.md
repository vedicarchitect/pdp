## ADDED Requirements

### Requirement: Create alert
The system SHALL allow users to create price, Greek, or P&L alerts via REST API with security_id, condition type, threshold, and channels.

#### Scenario: Create price alert
- **WHEN** user POST /alerts with {security_id, condition: "PRICE_GT", threshold: 100.50, channels: ["WS"]}
- **THEN** alert is stored in DB with status "ARMED" and evaluator subscribes to ticks for that security_id

#### Scenario: Create delta alert
- **WHEN** user POST /alerts with {security_id, condition: "DELTA_GT", threshold: 0.5, channels: ["WS"]}
- **THEN** alert is stored in DB with status "ARMED" and evaluator subscribes to position updates for that security_id

#### Scenario: Invalid condition type
- **WHEN** user POST /alerts with condition: "CUSTOM_EXPR"
- **THEN** API rejects with 400 Bad Request (condition type not in enum)

### Requirement: Update alert
The system SHALL allow users to update alert threshold and channels via PATCH /alerts/{id}.

#### Scenario: Update threshold
- **WHEN** user PATCH /alerts/123 with threshold: 105.00
- **THEN** alert threshold is updated; status remains ARMED; evaluator re-evaluates on next tick

#### Scenario: Update channels
- **WHEN** user PATCH /alerts/123 with channels: ["WS", "Telegram"]
- **THEN** alert channels list is updated; once Telegram is implemented, notifications use both channels

### Requirement: Delete alert
The system SHALL allow users to delete alerts via DELETE /alerts/{id}.

#### Scenario: Delete alert
- **WHEN** user DELETE /alerts/123
- **THEN** alert is removed from DB; evaluator unsubscribes if no other alerts exist for that security_id

### Requirement: Evaluate alerts on tick
The system SHALL evaluate all armed alerts when a new tick arrives, and fire if condition crosses threshold.

#### Scenario: Price crosses threshold upward
- **WHEN** alert is ARMED with condition: "PRICE_GT" and threshold: 100.00, and price ticks from 99.50 → 100.50
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification to all channels (WS, etc.)

#### Scenario: Price crosses threshold downward
- **WHEN** alert is ARMED with condition: "PRICE_LT" and threshold: 100.00, and price ticks from 100.50 → 99.50
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification to all channels

#### Scenario: Price oscillates around threshold (no spam)
- **WHEN** alert is TRIGGERED, and price oscillates back above threshold, then back below
- **THEN** alert remains TRIGGERED; no duplicate notification sent until price stabilizes above/below threshold

#### Scenario: Price resolves (alert de-triggers)
- **WHEN** alert is TRIGGERED with condition: "PRICE_GT" threshold: 100.00, and price falls back to 99.50
- **THEN** alert transitions to RESOLVED; no notification sent for de-trigger (v1 behavior)

### Requirement: Evaluate Greeks alerts
The system SHALL evaluate delta, gamma, vega alerts when position updates arrive.

#### Scenario: Delta crosses threshold
- **WHEN** alert is ARMED with condition: "DELTA_GT" threshold: 0.6, and position delta updates from 0.55 → 0.65
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification via WS

#### Scenario: Gamma threshold
- **WHEN** alert is ARMED with condition: "GAMMA_LT" threshold: 0.02, and position gamma updates to 0.015
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification via WS

### Requirement: Evaluate P&L alerts
The system SHALL evaluate P&L thresholds when position updates arrive.

#### Scenario: P&L profit target
- **WHEN** alert is ARMED with condition: "PNL_GT" threshold: 500.00, and position P&L updates from 400 → 550
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification via WS

#### Scenario: P&L stop-loss
- **WHEN** alert is ARMED with condition: "PNL_LT" threshold: -200.00, and position P&L updates from -100 → -250
- **THEN** alert transitions to TRIGGERED, evaluator pushes notification via WS

### Requirement: Push alerts via WebSocket
The system SHALL push alert notifications to authenticated WebSocket clients on /ws/alerts in real time.

#### Scenario: Connected client receives alert
- **WHEN** evaluator fires an alert with channels: ["WS"] and client is connected to /ws/alerts with auth token
- **THEN** client receives JSON message {id, security_id, condition, threshold, timestamp, status: "TRIGGERED"} within p99 ≤ 50ms

#### Scenario: Unauthenticated client cannot subscribe
- **WHEN** client connects to /ws/alerts without auth token
- **THEN** WebSocket is rejected with 401 Unauthorized

#### Scenario: Client reconnection backfill
- **WHEN** client reconnects to /ws/alerts after disconnect
- **THEN** client receives current state of all user's alerts (ARMED/TRIGGERED/RESOLVED) before new notifications

### Requirement: Telegram channel (deferred)
The system SHALL accept "Telegram" as a channel option and stub notification sending (log, do not send).

#### Scenario: Alert with Telegram channel
- **WHEN** user creates alert with channels: ["Telegram"]
- **THEN** alert is stored; evaluator logs notification intent; actual Telegram send is deferred (v2)

### Requirement: Alert state machine
The system SHALL maintain alert state as ARMED, TRIGGERED, or RESOLVED.

#### Scenario: Initial state
- **WHEN** alert is created
- **THEN** status is set to "ARMED"

#### Scenario: State transitions
- **WHEN** alert is ARMED and condition crosses
- **THEN** state → TRIGGERED
- **WHEN** alert is TRIGGERED and condition no longer crosses (price reverses, delta drops, etc.)
- **THEN** state → RESOLVED
- **WHEN** alert is RESOLVED and condition crosses again
- **THEN** state → TRIGGERED (re-arm and re-notify)

### Requirement: List user alerts
The system SHALL provide GET /alerts to list all alerts for the authenticated user.

#### Scenario: List alerts
- **WHEN** user GET /alerts
- **THEN** response contains array of all user's alerts with id, security_id, condition, threshold, channels, status, created_at

#### Scenario: Filter by status
- **WHEN** user GET /alerts?status=TRIGGERED
- **THEN** response contains only alerts with status = TRIGGERED

### Requirement: Evaluator latency
The system SHALL evaluate all active alerts and push notifications within p99 ≤ 50ms of tick arrival.

#### Scenario: Latency budget
- **WHEN** tick arrives at evaluator
- **THEN** all condition evaluations, state transitions, and WebSocket pushes complete within 50ms (p99)

### Requirement: Alert storage
The system SHALL persist alerts in PostgreSQL with schema: id, user_id, security_id, condition, threshold, channels (JSON array), status, created_at, updated_at.

#### Scenario: Persistence
- **WHEN** alert is created or updated
- **THEN** changes are persisted to DB; on server restart, all alerts are loaded and evaluator resumes
