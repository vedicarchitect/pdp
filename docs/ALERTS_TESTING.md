# Alerts Engine — Testing & Integration Guide

## What Was Fixed

### 1. WebSocket Session Access ✓
- **Issue:** `ws.app.state.db_session()` did not exist
- **Fix:** Updated to use `get_session_maker()` from `pdp.db.session`
- **File:** `src/pdp/alerts/ws.py:118`

### 2. AlertEvaluator Wiring ✓
- **Issue:** AlertEvaluator was defined but never instantiated or subscribed to ticks
- **Fixes:**
  - Modified `TickRouter` to accept `alert_evaluator` parameter
  - Instantiate `AlertEvaluator` in `main.py` lifespan
  - Register notification callback
  - Call `await alert_evaluator.load_alerts()` on startup
  - Pass evaluator to TickRouter constructor
  - Call `evaluate_price()` for each tick in `TickRouter._handle()`
- **Files:** `src/pdp/main.py`, `src/pdp/market/router.py`

### 3. Authentication Stub ✓
- **Issue:** Routes and WebSocket used hardcoded user IDs
- **Fixes:**
  - Updated REST routes to extract Authorization header
  - Updated WebSocket to require token (query param or header)
  - Added logging for missing auth
  - Prepared for JWT validation (marked with TODO for v2)
- **Files:** `src/pdp/alerts/routes.py`, `src/pdp/alerts/ws.py`

---

## Prerequisites for Testing

1. **Database Migration**
   ```bash
   alembic upgrade head
   ```
   This creates the `alerts` table with schema:
   - `id` (primary key)
   - `user_id` (indexed)
   - `security_id`
   - `condition` (enum: PRICE_GT, PRICE_LT, etc.)
   - `threshold` (numeric)
   - `channels` (JSON array)
   - `status` (ARMED, TRIGGERED, RESOLVED)
   - `created_at`, `updated_at`

2. **Start Application**
   ```bash
   uvicorn src.pdp.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Enable Market Feed** (optional, for live evaluation)
   Set environment variables:
   - `DHAN_CLIENT_ID`
   - `DHAN_ACCESS_TOKEN`

   Without these, AlertEvaluator is instantiated but not called (market feed skipped).

---

## Testing Workflow

### Test 1: Create Alert via REST API

**Setup:** Start the application and database

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{
    "security_id": "NSE_EQ_SBIN",
    "condition": "PRICE_GT",
    "threshold": 500.00,
    "channels": ["WS"]
  }'
```

**Expected Response (201 Created):**
```json
{
  "id": 1,
  "user_id": "user_123",
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.00",
  "channels": ["WS"],
  "status": "ARMED",
  "created_at": "2026-06-08T12:00:00Z",
  "updated_at": "2026-06-08T12:00:00Z"
}
```

✓ **Verifies:** REST endpoint, database persistence, request validation

---

### Test 2: List Alerts

**Request:**
```bash
curl http://localhost:8000/api/v1/alerts \
  -H "Authorization: Bearer test-token"
```

**Expected Response:**
```json
[
  {
    "id": 1,
    "user_id": "user_123",
    "security_id": "NSE_EQ_SBIN",
    "condition": "PRICE_GT",
    "threshold": "500.00",
    "channels": ["WS"],
    "status": "ARMED",
    ...
  }
]
```

✓ **Verifies:** List endpoint, filtering by user_id

---

### Test 3: WebSocket Connection & Backfill

**Connect to WebSocket:**
```javascript
// Browser console
const ws = new WebSocket('ws://localhost:8000/ws/alerts?token=test-token');

ws.onopen = () => {
  console.log('Connected');
};

ws.onmessage = (event) => {
  console.log('Received:', JSON.parse(event.data));
};

ws.onerror = (error) => {
  console.error('Error:', error);
};
```

**Expected Messages (on connect):**
```json
{
  "id": 1,
  "security_id": "NSE_EQ_SBIN",
  "condition": "PRICE_GT",
  "threshold": "500.00",
  "status": "ARMED",
  "channels": ["WS"],
  "created_at": "2026-06-08T12:00:00Z"
}
```

✓ **Verifies:** WebSocket authentication, backfill state on connect

---

### Test 4: Alert Evaluation (Paper Mode)

**Setup:** Ensure tick data is available

**Step 1: Create alert**
```bash
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{
    "security_id": "NSE_EQ_SBIN",
    "condition": "PRICE_GT",
    "threshold": 500.00,
    "channels": ["WS"]
  }'
```

**Step 2: Trigger tick** (via market feed or test)
```python
# In tests or manual trigger:
from decimal import Decimal
from pdp.market.models import Tick

tick = Tick(
    security_id="NSE_EQ_SBIN",
    exchange_segment="NSE_EQ",
    ltp=Decimal("501.00"),  # > 500.00 threshold
    volume=1000,
    oi=0,
    ltt=datetime.now(UTC)
)
# This would trigger alert via tick_router
```

**Step 3: Check alert status**
```bash
curl http://localhost:8000/api/v1/alerts/1 \
  -H "Authorization: Bearer test-token"
```

**Expected:** Status changes from `ARMED` to `TRIGGERED`

✓ **Verifies:** Condition evaluation, state machine, alert evaluation on tick

---

### Test 5: State Transitions

**Initial state:** Create alert with PRICE_GT condition, threshold 500

1. **Price below threshold (499):** Status = ARMED
2. **Price crosses up (501):** Status = TRIGGERED (notification sent)
3. **Price drops (499):** Status = RESOLVED
4. **Price crosses up again (501):** Status = TRIGGERED (re-armed)

✓ **Verifies:** State machine (ARMED → TRIGGERED → RESOLVED → TRIGGERED)

---

### Test 6: Update Alert

**Request:**
```bash
curl -X PATCH http://localhost:8000/api/v1/alerts/1 \
  -H "Authorization: Bearer test-token" \
  -H "Content-Type: application/json" \
  -d '{
    "threshold": 505.00,
    "channels": ["WS", "TELEGRAM"]
  }'
```

**Expected:** Alert updated, next evaluation uses new threshold

✓ **Verifies:** Update endpoint, persistence, evaluator re-evaluation

---

### Test 7: Delete Alert

**Request:**
```bash
curl -X DELETE http://localhost:8000/api/v1/alerts/1 \
  -H "Authorization: Bearer test-token"
```

**Expected:** 204 No Content, alert removed from DB

✓ **Verifies:** Delete endpoint, database removal

---

### Test 8: Authentication

**Request without token:**
```bash
curl http://localhost:8000/api/v1/alerts
```

**Expected:** 200 OK (v1 allows unauthenticated for demo; logs warning)

**WebSocket without token:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/alerts');
// Expected: 4001 error, connection closed with "Unauthorized: missing token"
```

✓ **Verifies:** Auth header parsing, WebSocket rejection

---

## Unit Tests

Run tests:
```bash
pytest src/pdp/alerts/tests.py -v
```

**Coverage:**
- ✓ AlertCondition enum validation
- ✓ AlertEvaluator condition logic (price, Greeks, P&L)
- ✓ State machine transitions (ARMED → TRIGGERED → RESOLVED)
- ✓ AlertNotification payload format
- ✓ Notification callbacks

---

## Known Limitations (v1)

1. **Authentication:** JWT validation not implemented (uses placeholder "user_123")
   - **v2:** Add proper JWT extraction and validation
   
2. **User-specific routing:** Notifications broadcast to all; not per-user yet
   - **v2:** Query alert user_id and publish to specific user's hub
   
3. **Telegram channel:** Stub only (logs, does not send)
   - **v2:** Implement actual Telegram delivery
   
4. **Alert history:** No audit log or history
   - **v2:** Add triggered_at, resolved_at timestamps
   
5. **Greeks/P&L evaluation:** Hooked up in code but requires position ledger integration
   - **v2:** Wire to portfolio service for position updates

---

## Deployment Checklist

- [ ] Database migration applied (`alembic upgrade head`)
- [ ] DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN set (or app starts without market feed)
- [ ] AlertEvaluator instantiated in main.py lifespan
- [ ] TickRouter receives alert_evaluator parameter
- [ ] WebSocket authentication validates tokens (or stub passes)
- [ ] REST endpoints check Authorization header
- [ ] Unit tests pass (`pytest src/pdp/alerts/tests.py`)
- [ ] Manual end-to-end test: create alert → trigger tick → WebSocket receives notification

---

## Troubleshooting

### WebSocket connection refused
- Check: `ws://` (not `wss://`) for local testing
- Check: Token parameter or Authorization header present
- Check: Server logs for `alerts_ws_connected` / `alerts_ws_error`

### Alert not evaluating after tick
- Check: `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` set (enables market feed)
- Check: AlertEvaluator in `app.state.alert_evaluator`
- Check: TickRouter has `alert_evaluator` parameter
- Server logs should show `market_feed_started, alerts_engine=enabled`

### Alert status not updating
- Check: Database has alert with correct security_id
- Check: Tick arrives for correct security_id
- Check: Condition type matches (PRICE_GT, PRICE_LT, etc.)
- Check: Threshold is numeric (not string)

### Authentication always fails
- WebSocket: Include `?token=` query parameter (even if not validated)
- REST: Include `Authorization: Bearer` header (even with dummy token)
- v1 logs warnings for missing auth but allows requests

---

## Next Steps (v2)

1. Implement JWT validation with proper user extraction
2. Add user_id-based WebSocket publishing (alerts_hub.publish per user)
3. Implement Telegram delivery
4. Add position update integration (evaluate Greeks, P&L)
5. Add alert history and audit logging
6. Add composite alerts (multiple conditions)
7. Add alert snooze/dismiss functionality
8. Add alert templates (common thresholds)
