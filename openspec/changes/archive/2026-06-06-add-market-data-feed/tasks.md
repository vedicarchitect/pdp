## 1. Schema

- [ ] 1.1 Alembic migration `0003_market_bars.py` creating hypertable + compression + retention policies
- [x] 1.2 Alembic migration `0004_subscriptions.py` with `subscriptions(security_id, exchange_segment, added_at)`

## 2. Dhan WS Adapter

- [x] 2.1 `src/pdp/market/dhan_ws.py` — connect, auth, binary frame decode via `msgspec.Struct`
- [x] 2.2 Exponential reconnect (1→2→4→…→30s cap)
- [x] 2.3 Subscribe / unsubscribe API; persist to `subscriptions` table
- [x] 2.4 Emit decoded ticks to bounded `asyncio.Queue` (1000)

## 3. Tick Router

- [x] 3.1 `src/pdp/market/router.py` — consume queue, fan out to Redis + BarAggregator + WS Hub
- [x] 3.2 Redis: `SET ltp:<id> <ltp> EX 5` + `PUBLISH tick.<id> <json>`
- [x] 3.3 Drop-oldest on backpressure with structured warning

## 4. Bar Aggregator

- [ ] 4.1 `src/pdp/market/bars.py` — per (security_id, timeframe) `BarBuilder` using Polars-friendly buffers
- [ ] 4.2 On boundary cross: emit `BarClosed` event; reset builder
- [ ] 4.3 Batched Timescale writer (1s flush or 500-row buffer) using `asyncpg.copy_records_to_table`
- [ ] 4.4 `XADD bars.<id>.<tf>` per closed bar

## 5. WS Hub + REST

- [ ] 5.1 `src/pdp/market/ws.py` — `/ws/market` endpoint, per-client queue (bounded=50)
- [ ] 5.2 Subscribe/unsubscribe JSON protocol
- [x] 5.3 `src/pdp/market/routes.py` — `GET /api/v1/ltp`, `GET /api/v1/bars/{security_id}` (ltp done; bars deferred to add-market-data-bars)

## 6. Tests + Load

- [ ] 6.1 Unit tests for BarBuilder boundaries (5m crossing 09:14:59 → 09:15:00)
- [ ] 6.2 Integration test: in-memory fake tick stream → verify Redis + DB + WS message
- [ ] 6.3 `loadtest/locustfile.py` — 200 simulated WS subscribers
- [ ] 6.4 Document p99 measurement procedure in `loadtest/README.md`

## 7. Validation

- [ ] 7.1 `openspec validate --strict add-market-data-feed`
- [ ] 7.2 Live smoke during market hours: subscribe to NIFTY index, observe ticks in <60s
