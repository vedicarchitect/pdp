## Why

TimescaleDB is over-engineered for this project's bar storage needs and adds operational cost; MongoDB 7's native time-series collections (already provisioned in Phase 2) provide equivalent query performance with a simpler stack. Consolidating all historical market data into MongoDB removes the dual-database write path and sets the foundation for options-chain analytics.

## What Changes

- `src/pdp/market/bar_writer.py` — replace `asyncpg` COPY-based writes to `market_bars` hypertable with motor inserts into the `market_bars` time-series collection
- `src/pdp/market/bars_router.py` — replace TimescaleDB query with a MongoDB aggregation pipeline for `/api/v1/bars`
- `alembic/versions/0008_drop_market_bars.py` — migration that drops the `market_bars` hypertable and its associated TimescaleDB objects
- `pyproject.toml` / `uv.lock` — remove `asyncpg` if no longer used elsewhere (check first)
- `docker-compose.yml` — optionally remove TimescaleDB service if PG is still needed for ledger; keep plain `postgres:16` or retain timescale image (decision in design)

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `market-bars`: storage backend changes from TimescaleDB to MongoDB time-series; query interface (`/api/v1/bars`) and WebSocket fan-out contract remain identical — only persistence layer changes

## Impact

- **Code**: `bar_writer.py`, `bars_router.py`, `main.py` lifespan (db handle replaced by mongo db), Alembic migration 0008
- **APIs**: `/api/v1/bars` — no contract change, same query params and response shape
- **Dependencies**: `motor` already present; `asyncpg` may be dropped if unused elsewhere
- **Infrastructure**: TimescaleDB extension no longer required for bar storage; Postgres still needed for ledger tables (orders, positions, instruments)
- **Tests**: existing bar writer / bars router tests updated to mock motor instead of asyncpg
