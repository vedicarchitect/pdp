## 1. Database Setup

- [x] 1.1 Create alerts table migration (id, user_id, security_id, condition, threshold, channels JSON, status, created_at, updated_at)
- [x] 1.2 Create indices on (user_id, status) and (security_id, condition)
- [x] 1.3 Add foreign key constraints to users and securities tables

## 2. Types & Models

- [x] 2.1 Define AlertCondition enum (PRICE_GT, PRICE_LT, DELTA_GT, DELTA_LT, GAMMA_GT, GAMMA_LT, VEGA_GT, VEGA_LT, PNL_GT, PNL_LT)
- [x] 2.2 Define AlertChannel enum (WS, Telegram)
- [x] 2.3 Define AlertStatus enum (ARMED, TRIGGERED, RESOLVED)
- [x] 2.4 Create Alert model/dataclass with validation (condition in enum, threshold numeric, channels non-empty)

## 3. Evaluator Core

- [x] 3.1 Create AlertEvaluator class that subscribes to market engine tick feed
- [x] 3.2 Implement condition evaluation logic for price conditions (PRICE_GT, PRICE_LT)
- [x] 3.3 Implement condition evaluation for Greeks (DELTA_GT, DELTA_LT, etc.)
- [x] 3.4 Implement condition evaluation for P&L (PNL_GT, PNL_LT)
- [x] 3.5 Implement state machine: ARMED → TRIGGERED → RESOLVED → TRIGGERED (re-arm on re-cross)
- [x] 3.6 Add debounce logic to prevent alert spam (fire once per state transition, not per tick)
- [x] 3.7 Subscribe AlertEvaluator to market engine and position ledger feeds on startup

## 4. REST API Endpoints

- [x] 4.1 Implement POST /alerts (create) with request validation (condition, threshold, channels, security_id)
- [x] 4.2 Implement GET /alerts (list) with optional status filter
- [x] 4.3 Implement GET /alerts/{id} (fetch single alert)
- [x] 4.4 Implement PATCH /alerts/{id} (update threshold/channels)
- [x] 4.5 Implement DELETE /alerts/{id} (delete alert)
- [x] 4.6 Add authentication middleware to all alert endpoints (user_id from token)
- [x] 4.7 Add request/response logging via structlog

## 5. WebSocket Channel

- [x] 5.1 Create /ws/alerts WebSocket endpoint with authentication (reject 401 if no token)
- [x] 5.2 Implement client registry (map client_id → WebSocket connection)
- [x] 5.3 On alert TRIGGERED, push JSON {id, security_id, condition, threshold, timestamp, status} to all connected clients
- [x] 5.4 On client connect, backfill current alert state (all user's alerts with status)
- [x] 5.5 On client disconnect, clean up registry entry
- [x] 5.6 Implement graceful connection close on auth token expiry

## 6. Channel Integration

- [x] 6.1 Create abstract Channel class with send(alert_notification) method
- [x] 6.2 Implement WSChannel (pushes via WebSocket)
- [x] 6.3 Implement TelegramChannel stub (logs notification, does not send; placeholder for v2)
- [x] 6.4 Update AlertEvaluator.notify() to route notifications to appropriate channels

## 7. Integration & Startup

- [x] 7.1 Wire AlertEvaluator into market engine startup (subscribe to ticks, load alerts from DB)
- [x] 7.2 Add graceful shutdown for AlertEvaluator (unsubscribe from feeds)
- [x] 7.3 Add environment variable to enable/disable alerts engine (defaults to enabled)

## 8. Testing

- [x] 8.1 Unit test: AlertCondition enum validation
- [x] 8.2 Unit test: AlertEvaluator condition logic (price, Greeks, P&L)
- [x] 8.3 Unit test: State machine transitions (ARMED → TRIGGERED → RESOLVED)
- [x] 8.4 Integration test: Create alert via REST, verify stored in DB
- [x] 8.5 Integration test: Tick arrives, alert fires, WebSocket receives notification
- [x] 8.6 Integration test: Update alert threshold, re-evaluate on next tick
- [x] 8.7 Integration test: Delete alert, evaluator stops tracking security_id
- [x] 8.8 Integration test: Client reconnects to /ws/alerts, receives backfill
- [x] 8.9 Latency test: Measure p99 tick → notification time (target ≤ 50ms)

## 9. Documentation & QA

- [x] 9.1 Add API documentation (OpenAPI spec / Swagger for REST endpoints)
- [x] 9.2 Add WebSocket message format documentation
- [x] 9.3 Update README with alerts feature description
- [x] 9.4 Manual QA: Create price alert, modify price in paper engine, verify UI receives notification
- [x] 9.5 Manual QA: Test alert state transitions (ARMED → TRIGGERED → RESOLVED)
- [x] 9.6 Manual QA: Verify Telegram channel logs (stub behavior in v1)
