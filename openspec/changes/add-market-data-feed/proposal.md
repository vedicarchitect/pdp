## Why

Real-time monitoring of intraday/positional/portfolio is the platform's headline feature. We need a hot path that streams Dhan ticks through Redis to WebSocket subscribers and persists OHLCV bars to TimescaleDB — under a 50ms tick-to-fan-out budget.

## What Changes

- Dhan ticker WebSocket adapter (single asyncio task) decoding binary frames with `msgspec`.
- Tick publish to Redis Pub/Sub channel `tick.<security_id>` + hot LTP cache `ltp:<security_id>` (TTL 5s).
- In-process bar aggregator emits 1m/5m/15m/30m/1H bars on close.
- Closed bars written to TimescaleDB hypertable `market_bars` via batched `COPY` (every 1s flush or 500-row buffer).
- WebSocket `/ws/market` accepting `{action, security_ids, timeframes}` for subscribe/unsubscribe; fans out ticks + bar-close events with drop-oldest backpressure (max 50 queued per client).
- REST `GET /api/v1/ltp?ids=...` (Redis read) and `GET /api/v1/bars/{security_id}?tf=5m&limit=N` (Timescale read).
- Locust load script documenting tick→WS p99 ≤ 50ms.

## Capabilities

### New Capabilities

- `market-data`: Tick + bar pipeline, Redis hot cache, WS fan-out, REST snapshots.

### Modified Capabilities

(none — depends on `platform-core` + `instrument-registry`)

## Impact

- New Alembic migration creating TimescaleDB hypertable `market_bars` (PRIMARY KEY `(security_id, timeframe, bar_time)`).
- New deps: `websockets`, `msgspec` (already listed), `redis[hiredis]`.
- Adds an outbound persistent WS to Dhan; respects rate limits (≤ 5000 instruments per connection per Dhan limits).
- Locust optional dev dep.
