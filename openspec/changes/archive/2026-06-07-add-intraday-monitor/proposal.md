## Why

(STUB.) Intraday traders need a dense, sub-second-updating dashboard combining open positions, live LTP/Greeks, P&L, strategy state, and a one-click kill-switch.

## What Changes

- Dedicated `/intraday` page consuming `/ws/market`, `/ws/orders`, `/ws/portfolio`.
- Per-strategy P&L panel + risk caps (max-loss-per-day enforce).
- Global kill-switch endpoint `POST /api/v1/risk/kill` (cancels all open orders + flattens intraday positions).
- Alert pills (price hit, P&L threshold, time-stop).

## Capabilities

### New Capabilities

- `intraday-monitor`: Live intraday dashboard + risk caps + kill-switch.

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `order-execution`, `strategy-host`, and the frontend skeleton. Authored after those ship.
