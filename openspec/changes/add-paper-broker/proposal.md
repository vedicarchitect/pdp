## Why

Paper trading is the v1 default and the only safe surface for testing strategies, monitoring, and P&L. A deterministic paper-fill engine — driven by real tick stream — gives us a realistic harness without touching live broker.

## What Changes

- New `orders`, `trades`, `positions` tables with full state machines.
- `OrderRouter` chooses paper vs. live based on `LIVE` env + broker availability; v1 always routes to paper.
- Paper-fill engine consumes ticks from Redis: MARKET fills at next tick mid + configurable slippage_bps; LIMIT fills when LTP crosses; SL / SL-M honored.
- Cost model: STT, exchange fee, GST, brokerage applied per fill from `broker_costs` config table.
- REST: `POST /api/v1/orders`, `GET /api/v1/orders`, `DELETE /api/v1/orders/{id}` (cancel), `GET /api/v1/positions`, `GET /api/v1/trades`.
- WebSocket `/ws/orders` for order/trade/position event stream.
- Mode banner contract: every API response includes `X-Trade-Mode: PAPER` (or `LIVE`) header.

## Capabilities

### New Capabilities

- `order-execution`: Order lifecycle, paper-fill engine, positions accounting, cost model, broker-mode gate.

### Modified Capabilities

(none — depends on `platform-core`, `instrument-registry`, `market-data`)

## Impact

- 3 new Alembic migrations for `orders`, `trades`, `positions`, `broker_costs`.
- No external broker integration in this change (that's `add-dhan-broker`).
- Strategy host (`add-strategy-host`) will consume the `OrderRouter` interface.
