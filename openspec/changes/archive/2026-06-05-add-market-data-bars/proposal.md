## Why

The first market-data slice (`add-market-data-feed`) delivers live tick ingestion and an LTP hot cache, but strategies and the UI need historical and real-time OHLCV bars — not just spot prices. Bar aggregation, TimescaleDB persistence, WebSocket fan-out, and a bars REST endpoint are the missing layer between raw ticks and any consumer (chart, strategy, backtest).

## What Changes

- `src/pdp/market/bars.py` — `BarBuilder` per `(security_id, timeframe)` that accumulates ticks into OHLCV bars on wall-clock boundaries (1m, 5m, 15m, 30m, 1H); emits a `BarClosed` event on boundary crossing.
- `src/pdp/market/bar_writer.py` — batched asyncpg `COPY` writer that flushes closed bars to the `market_bars` TimescaleDB hypertable (1-second or 500-row trigger).
- `src/pdp/market/ws.py` — `/ws/market` WebSocket endpoint; per-client subscription to security IDs + timeframes; per-client queue bounded at 50 messages, drop-oldest on overflow.
- `src/pdp/market/router.py` — extend `TickRouter._handle` to call `BarAggregator.push(tick)` and push closed bars to Redis streams (`XADD bars.<id>.<tf>`).
- `alembic/versions/0003_market_bars.py` — creates `market_bars` hypertable with compression after 7 days and drop-chunks after 2 years.
- `src/pdp/market/routes.py` — add `GET /api/v1/bars/{security_id}?tf=1m&limit=375` endpoint reading from TimescaleDB.
- `tests/market/test_bar_builder.py` — unit tests for boundary crossing and partial bar state.
- `tests/market/test_bar_integration.py` — end-to-end: fake tick stream → Redis stream + DB rows + WS message.
- `loadtest/locustfile.py` + `loadtest/README.md` — 200-subscriber WS load test documenting p99 ≤ 50ms.

## Capabilities

### New Capabilities

- `market-bars`: OHLCV bar aggregation from tick stream; TimescaleDB persistence; Redis stream fan-out; WebSocket delivery to subscribers; REST historical query.

### Modified Capabilities

- `market-data`: Extends existing tick-pipeline requirements — `TickRouter` now routes closed bars in addition to raw ticks; adds WebSocket endpoint and bars REST endpoint to the market-data API surface.

## Impact

- **New dependency**: `asyncpg` direct (already in `pyproject.toml` via SQLAlchemy async extras) — used for `copy_records_to_table`.
- **Alembic**: migration 0003 (previously reserved slot) for `market_bars` hypertable.
- **Redis**: new key pattern `bars.<security_id>.<tf>` (XADD stream per timeframe).
- **FastAPI**: `/ws/market` WebSocket route + `GET /api/v1/bars/{security_id}` REST route added.
- **TickRouter**: gains `BarAggregator` dependency — zero impact on existing LTP/pub-sub path.
- **TimescaleDB**: requires TimescaleDB extension enabled (already present in `docker-compose.yml`).
