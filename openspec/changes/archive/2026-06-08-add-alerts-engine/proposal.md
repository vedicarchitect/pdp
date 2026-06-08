## Why

(STUB.) Users need price/Greek/P&L alerts surfaced fast — in the UI immediately, and (later) via Telegram/WhatsApp.

## What Changes

- `alerts` table (security_id, condition, threshold, channels, status).
- Evaluator subscribes to ticks/positions and emits when condition crosses.
- `/ws/alerts` push channel; Telegram out (deferred).

## Capabilities

### New Capabilities

- `alerts`: Configurable price/Greek/P&L alerts with WS push (and later Telegram).

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `order-execution`.
