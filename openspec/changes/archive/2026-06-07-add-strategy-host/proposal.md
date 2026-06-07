## Why

(STUB.) Strategies need a pluggable runtime with consistent lifecycle hooks (`on_bar`, `on_tick`, `on_fill`), a clean `OrderRouter` injection, and isolation so a runaway strategy can't block the hot path.

## What Changes

- `Strategy` ABC with `on_init`, `on_bar(security_id, timeframe, bar)`, `on_tick(security_id, tick)`, `on_order_fill(trade)`, `on_shutdown`.
- Strategy registry + YAML config (`strategies/<id>.yaml`) for params, watchlist, risk caps.
- Each strategy runs in its own asyncio task with a bounded inbox queue.
- `GET /api/v1/strategies` + `POST /api/v1/strategies/{id}/start|stop`.

## Capabilities

### New Capabilities

- `strategy-host`: Pluggable strategy runtime with lifecycle hooks and per-strategy isolation.

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `order-execution`.
