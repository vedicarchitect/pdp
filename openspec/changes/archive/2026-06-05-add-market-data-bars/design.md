## Context

The tick pipeline (`add-market-data-feed`) is live: ticks arrive via Dhan WS, are decoded into `Tick` dataclasses, stored in Redis LTP cache, and published via Redis pub/sub. `TickRouter._handle` has empty stubs for bar aggregation and WS fan-out.

This change fills those stubs. The constraint is the latency budget: tick → WS-out p99 ≤ 50 ms on a single instrument. All hot-path work must be CPU-bound-free on the asyncio event loop; any heavy I/O (TimescaleDB writes) is batched and off the critical path.

## Goals / Non-Goals

**Goals:**
- Aggregate ticks into OHLCV bars for 1m / 5m / 15m / 30m / 1H timeframes
- Persist closed bars to TimescaleDB `market_bars` hypertable
- Fan closed bars out to subscribed WebSocket clients with drop-oldest backpressure
- Push closed bars to Redis streams (`XADD bars.<id>.<tf>`) for downstream consumers
- `GET /api/v1/bars/{security_id}?tf=&limit=` REST endpoint
- Unit tests for bar boundary logic; integration test with fake tick stream; Locust load test

**Non-Goals:**
- Multi-process fan-out (single-process `uvicorn --workers 1` at v1)
- Rolling-window indicators (VWAP, EMA, RSI) — those belong in `options-analytics` / `strategy-host`
- Tick-level persistence (TimescaleDB `ticks` hypertable) — deferred
- Replay/backfill from historical data

## Decisions

### D1: BarBuilder is a plain Python class, not async

Each `BarBuilder(security_id, timeframe)` is stateful (open/high/low/close/volume/OI accumulators). `push(tick)` is synchronous and executes entirely in the asyncio event loop without yielding. This keeps the hot path allocation-free: no awaits, no task spawning per tick.

**Alternatives considered:**
- Polars rolling aggregation: elegant for batch, but requires DataFrame allocation per flush — too heavy for 100+ instruments at 50ms budget.
- Per-timeframe asyncio task: adds queue-per-builder overhead; synchronous push is simpler and fast enough.

### D2: One `BarAggregator` owns all BarBuilders

`BarAggregator` holds `dict[(security_id, timeframe), BarBuilder]` and is the single entry point called by `TickRouter`. It creates builders on first tick for a security_id. This avoids any subscription bookkeeping inside BarBuilder.

### D3: Bar boundary by wall-clock UTC truncation

A bar closes when `tick.ltt.minute // timeframe_minutes != current_bar.open_time.minute // timeframe_minutes` (for sub-hour TFs) or when the hour changes (1H). This matches standard exchange bar definitions without needing a separate clock task.

**Alternative:** timer-based (fire every N minutes) — simpler but misses "no tick in interval" bars and is harder to unit-test deterministically.

### D4: Batched asyncpg COPY for TimescaleDB writes

Closed bars accumulate in a `deque` inside `BarWriter`. A background asyncio task flushes via `asyncpg.copy_records_to_table` every 1 second **or** when the buffer hits 500 rows. This is the only place we use raw `asyncpg` (bypassing SQLAlchemy) because COPY is ~10× faster than multi-row INSERT for time-series data.

**Alternative:** SQLAlchemy `insert().values(...)` — simpler but 3-5× slower at sustained tick rates.

### D5: Per-client WebSocket queue (bounded=50, drop-oldest)

Each connected WS client gets its own `asyncio.Queue(maxsize=50)`. When full, the oldest item is discarded (same pattern as the tick queue). This decouples slow clients from fast ones and prevents any single client from blocking the fan-out loop.

**Alternative:** shared broadcast with asyncio.Condition — simpler but one blocked client stalls all others.

### D6: Redis XADD for bar fan-out (not pub/sub)

Bars use Redis Streams (`XADD`) rather than pub/sub because streams are persistent: a late-joining consumer (strategy engine, backtest) can read from an offset. Pub/sub is fire-and-forget. Stream keys: `bars.<security_id>.<tf>` (e.g., `bars.13.1m`), MAXLEN ~= 1000 per stream.

## Risks / Trade-offs

- **Wall-clock boundary drift**: If ticks arrive with stale `ltt` (Dhan WS can lag), the last tick before bar close might carry a time in the next bar window. Mitigation: use `ltt` for bar placement but cap at `ts_recv` — if `ltt > ts_recv + 2s`, fall back to `ts_recv`.
- **BarWriter backlog**: If TimescaleDB is slow (cold start), the deque can grow unbounded. Mitigation: cap deque at 10,000 rows; log `bar_writer_overflow` and drop oldest.
- **WS client count**: At 500 clients × 50 bars/s, fan-out is 25,000 queue-puts/s. Single-process asyncio can handle this at v1; horizontal scaling (Redis stream consumer groups) is deferred.
- **Missing 0003 migration slot**: The migration chain currently goes 0001→0002→0004. Migration 0003 was reserved for `market_bars` — we fill it here. The `down_revision` must be `"0002"` to slot correctly between subscriptions (0004) and instrument tables.

## Migration Plan

1. Apply `alembic upgrade 0003` (creates `market_bars` hypertable). Requires TimescaleDB extension — already in `docker-compose.yml`.
2. Deploy app — BarAggregator starts automatically as part of `TickRouter` on first tick.
3. No data migration needed (table is new).
4. Rollback: `alembic downgrade 0002` drops `market_bars` (no production data at v1).

## Open Questions

- **Compression policy timing**: 7-day compression was chosen arbitrarily. Should verify this aligns with actual query patterns once the UI chart is implemented.
- **Timeframe configurability**: Hard-coded to `[1, 5, 15, 30, 60]` minutes. If strategies need non-standard TFs (e.g., 3m), this needs a settings key.
