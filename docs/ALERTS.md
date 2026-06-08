# Alerts API Documentation

## Overview

The alerts engine provides real-time price, Greek, and P&L alerts for active traders. Alerts are evaluated on every market tick and position update, with notifications pushed to connected WebSocket clients.

## REST API Endpoints

### Create Alert

**Endpoint:** `POST /api/v1/alerts`

**Request:**
```json
{
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": 500.50,
  "channels": ["WS"]
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "user_id": "user_123",
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.50",
  "channels": ["WS"],
  "status": "ARMED",
  "created_at": "2026-06-08T12:00:00Z",
  "updated_at": "2026-06-08T12:00:00Z"
}
```

**Supported Conditions:**
- `PRICE_GT` / `PRICE_LT` — Price above/below threshold
- `DELTA_GT` / `DELTA_LT` — Delta above/below threshold
- `GAMMA_GT` / `GAMMA_LT` — Gamma above/below threshold
- `VEGA_GT` / `VEGA_LT` — Vega above/below threshold
- `PNL_GT` / `PNL_LT` — P&L above/below threshold

**Supported Channels:**
- `WS` — WebSocket push (real-time, instant)
- `TELEGRAM` — Telegram notification (deferred, stubbed in v1)

---

### List Alerts

**Endpoint:** `GET /api/v1/alerts?status=ARMED`

**Query Parameters:**
- `status` (optional) — Filter by status: `ARMED`, `TRIGGERED`, `RESOLVED`

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "user_id": "user_123",
    "security_id": "NSE_EQ_SBIN",
    "condition": "PRICE_GT",
    "threshold": "500.50",
    "channels": ["WS"],
    "status": "ARMED",
    "created_at": "2026-06-08T12:00:00Z",
    "updated_at": "2026-06-08T12:00:00Z"
  }
]
```

---

### Get Alert

**Endpoint:** `GET /api/v1/alerts/{alert_id}`

**Response (200 OK):**
```json
{
  "id": 1,
  "user_id": "user_123",
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.50",
  "channels": ["WS"],
  "status": "ARMED",
  "created_at": "2026-06-08T12:00:00Z",
  "updated_at": "2026-06-08T12:00:00Z"
}
```

---

### Update Alert

**Endpoint:** `PATCH /api/v1/alerts/{alert_id}`

**Request:**
```json
{
  "threshold": 505.00,
  "channels": ["WS", "TELEGRAM"]
}
```

**Response (200 OK):** Updated alert object

---

### Delete Alert

**Endpoint:** `DELETE /api/v1/alerts/{alert_id}`

**Response:** 204 No Content

---

## WebSocket API

### Connection

**Endpoint:** `ws://localhost:8000/ws/alerts`

**Authentication:** JWT token in query parameter or header
- Token extraction: `Authorization: Bearer <token>`

**Connection Flow:**
1. Client connects to `/ws/alerts`
2. Server validates auth token (401 if invalid)
3. Server sends backfill of current alert state
4. Server pushes real-time notifications as alerts fire

### Message Format — Backfill (On Connect)

Immediately after connection, server sends current state of all user's alerts:

```json
{
  "id": 1,
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.50",
  "status": "ARMED",
  "channels": ["WS"],
  "created_at": "2026-06-08T12:00:00Z"
}
```

### Message Format — Alert Trigger

When an alert condition is met:

```json
{
  "id": 1,
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.50",
  "timestamp": "2026-06-08T12:05:30.123456Z",
  "status": "TRIGGERED"
}
```

---

## Alert State Machine

```
ARMED (initial)
  ↓
  [condition crosses threshold]
  ↓
TRIGGERED
  ↓
  [condition no longer crossed]
  ↓
RESOLVED
  ↓
  [condition crosses threshold again]
  ↓
TRIGGERED (re-armed)
```

**State Transitions:**
- `ARMED` → `TRIGGERED`: When alert condition becomes true (crossing up/down)
- `TRIGGERED` → `RESOLVED`: When alert condition becomes false (crossing back)
- `RESOLVED` → `TRIGGERED`: Alert can re-trigger if condition crosses again
- No duplicate notifications during oscillation (debounce per state transition)

---

## Latency SLA

- **Tick → Notification:** p99 ≤ 50ms
- **Condition Evaluation:** O(1) per alert
- **WebSocket Push:** Non-blocking async broadcast

---

## Error Handling

### 400 Bad Request
- Invalid `condition` type
- Empty `channels` list
- Non-numeric `threshold`

### 401 Unauthorized
- Missing or invalid JWT token (WebSocket)
- Auth middleware rejects on REST endpoints

### 404 Not Found
- Alert doesn't exist
- Alert belongs to different user

### 409 Conflict
- Duplicate alert (same user_id, security_id, condition, threshold)

---

## Examples

### Create a Price Alert

```bash
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "security_id": "NSE_EQ_SBIN",
    "condition": "PRICE_LT",
    "threshold": 450.00,
    "channels": ["WS"]
  }'
```

### Create a Delta Alert

```bash
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "security_id": "NSE_OPT_SBIN_2600_CE",
    "condition": "DELTA_GT",
    "threshold": 0.70,
    "channels": ["WS"]
  }'
```

### WebSocket Client (JavaScript)

```javascript
const token = "your-jwt-token";
const ws = new WebSocket(`ws://localhost:8000/ws/alerts?token=${token}`);

ws.onmessage = (event) => {
  const alert = JSON.parse(event.data);
  console.log(`Alert ${alert.id} TRIGGERED on ${alert.security_id}:`, alert);
};

ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};
```
