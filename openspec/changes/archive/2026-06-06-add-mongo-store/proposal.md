## Why

The platform's approved architecture designates MongoDB 7 as the high-throughput warehouse for all historical market data (bars, option chains, pre-computed features), replacing TimescaleDB for time-series storage. Before any data can be migrated or ingested into Mongo, the driver, connection lifecycle, and core collections must exist. This change establishes that foundation without touching existing data paths.

## What Changes

- Add `motor` (async MongoDB driver) to project dependencies
- Add `mongo7` service to `docker-compose.yml`
- Add `MONGO_URI` / `MONGO_DB_NAME` settings to `src/pdp/settings.py`
- New package `src/pdp/mongo/` with a `client.py` singleton (connect/disconnect) and `collections.py` (collection accessors)
- Wire Mongo connect/disconnect into FastAPI app lifespan (`main.py`)
- Extend `/readyz` to ping MongoDB and report its health
- Create `market_bars` as a native time-series collection (MongoDB time-series with `timeField="ts"`, `metaField="metadata"`)
- Create `option_chains` as a standard collection with a TTL index on `captured_at` (30-day default)

## Capabilities

### New Capabilities

- `mongo-store`: MongoDB client lifecycle, collection setup, and `/readyz` health integration

### Modified Capabilities

- `platform-core`: `/readyz` now includes a `mongo` health check alongside the existing `db` (PostgreSQL) check

## Impact

- **New dependency**: `motor>=3.4`
- **docker-compose.yml**: new `mongo` service (port 27017, named volume `mongo_data`)
- **`src/pdp/settings.py`**: two new env vars (`MONGO_URI`, `MONGO_DB_NAME`)
- **`src/pdp/main.py`**: lifespan connects/disconnects motor client; `/readyz` handler updated
- **`src/pdp/mongo/`**: new package (no existing code modified)
- PostgreSQL, TimescaleDB, and all existing data paths are unchanged
