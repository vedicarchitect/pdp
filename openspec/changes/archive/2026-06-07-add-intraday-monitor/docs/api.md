# Intraday Monitor — API Reference

## POST /api/v1/risk/kill

Cancels all open orders and flattens all intraday positions atomically.

**Authentication:** No additional auth beyond standard session (same as other routes).

**Request body:** None.

**Response (200 OK — all succeeded) / 207 (partial failure):**
```json
{
  "status": "ok | partial",
  "cancelled_orders": [
    { "id": "ord-123", "security_id": "NIFTY25JUL24000CE", "strategy_id": "strangle-1" }
  ],
  "flattened_positions": [
    { "security_id": "NIFTY25JUL24000CE", "exchange_segment": "NSE_FO", "product": "INTRADAY", "qty_flattened": 50, "side": "SELL" }
  ],
  "errors": [],
  "executed_at": "2024-07-15T09:30:00.000000Z",
  "requester": { "ip": "127.0.0.1", "ts": "2024-07-15T09:30:00.000000Z" }
}
```

| Field | Type | Description |
|---|---|---|
| `status` | `"ok" \| "partial"` | `"partial"` if any cancel/flatten step failed; HTTP 207 returned |
| `cancelled_orders` | object[] | List of orders successfully cancelled (`id`, `security_id`, `strategy_id`) |
| `flattened_positions` | object[] | List of positions closed (`security_id`, `qty_flattened`, `side`) |
| `errors` | string[] | Per-step error messages if any |
| `executed_at` | ISO8601 | Timestamp of execution |
| `requester` | object | Audit info: `{ip, ts}` |

**Behaviour:**
1. Query all orders with `status='open'` → cancel each via broker
2. Query all positions where `product IN ('INTRADAY', 'MIS')` and `net_qty != 0` → issue market orders to close
3. Positions with `product IN ('DELIVERY', 'NRML')` are skipped (overnight holds preserved)
4. All steps are logged with caller IP and timestamp for audit

**Error handling:** Returns `200` with `status: "partial"` if some steps failed. Never returns `500` — partial completion is surfaced through the `errors` array.

---

## GET /api/v1/risk/daily-loss

Returns today's realized + unrealized loss.

**Response (200 OK):**
```json
{
  "daily_loss": 12345.67,
  "day_start_pnl": 50000.0,
  "current_pnl": 37654.33,
  "per_strategy": {
    "strangle-1": { "realized": -5000, "unrealized": -7345.67 }
  }
}
```

---

## GET /api/v1/settings/risk

Returns configured risk cap values.

**Response (200 OK):**
```json
{
  "RISK_DAILY_LOSS_CAP_INR": 50000.0,
  "RISK_PER_STRATEGY_LOSS_CAP_INR": 20000.0,
  "RISK_SOFT_CAP_PCT": 80.0
}
```

These values are read from environment / `.env` at startup. They are read-only via this endpoint.

---

## WebSocket /ws/portfolio

Broadcasts position snapshots every ~100ms.

**Message format:**
```json
{
  "type": "portfolio_update",
  "positions": [
    {
      "security_id": "NSE:NIFTY25JUL24000CE",
      "exchange_segment": "NSE_FO",
      "product": "INTRADAY",
      "net_qty": 50,
      "avg_price": 123.45,
      "realized_pnl": 0.0,
      "unrealized_pnl": 500.0,
      "updated_at": "2024-07-15T09:30:00.000000+00:00",
      "ltp_stale": false
    }
  ],
  "summary": {
    "total_realized_pnl": 1200.0,
    "total_unrealized_pnl": 500.0,
    "day_pnl": 1700.0,
    "realized_loss_today": 0.0,
    "open_positions": 1
  }
}
```

**Notes:**
- `ltp_stale: true` means the Redis LTP key for that position has expired — mark with a visual indicator
- `realized_loss_today` is always `≥ 0` (it is a loss magnitude, not signed P&L)
- The summary is emitted on every broadcast. Frontend should read `summary.realized_loss_today` for risk cap computation

---

## Risk cap settings schema

Risk cap values are configured as environment variables (or in `.env`):

| Variable | Default | Description |
|---|---|---|
| `RISK_DAILY_LOSS_CAP_INR` | 50000 | Global daily loss cap in INR. Kill-switch auto-triggers at breach. |
| `RISK_PER_STRATEGY_LOSS_CAP_INR` | 20000 | Per-strategy daily loss cap in INR. |
| `RISK_SOFT_CAP_PCT` | 80 | Percentage of cap at which soft-cap UI warnings appear (yellow banner). |

To change: update `.env` and restart the server. Changes take effect on the next app startup.
