## Context

The platform has approved MongoDB 7 as the warehouse for all historical market data (bars, option chains, features). Before any data pipeline can write to Mongo, three things must exist: a running Mongo instance (docker-compose), an async Python driver wired into the FastAPI lifespan, and the target collections created with the right indexes. This change establishes all three without touching existing PostgreSQL/TimescaleDB paths.

Current state: no Mongo dependency anywhere in the codebase. PostgreSQL handles everything — orders/positions as a ledger (correct) and market bars via TimescaleDB (to be migrated in Phase 3).

## Goals / Non-Goals

**Goals:**
- `motor` client connects on startup, disconnects on shutdown, raises loudly if unreachable
- `market_bars` time-series collection created idempotently on startup
- `option_chains` collection created idempotently with TTL index on `captured_at`
- `/readyz` adds a `mongo` field alongside `db` and `redis`
- `docker-compose.yml` has a working `mongo` service developers can `docker compose up` immediately

**Non-Goals:**
- Writing any data to Mongo (Phase 3 migrates bars; Phase 4 ingest option chains)
- Repointing `bar_writer.py` or any existing data path
- Authentication / TLS for Mongo (localhost dev; production config is a follow-on)
- Replica-set mode (single-node is sufficient for Phase 2–3)

## Decisions

### D1: `motor` as the async driver (over `pymongo` or `beanie`)

`motor` wraps `pymongo` with native `asyncio` coroutines and is the officially recommended async driver. `beanie` (ODM) adds abstraction overhead that isn't needed when raw documents are fine; we can add it later if schema enforcement becomes important.

### D2: Singleton client on `app.state` (over dependency-injection per request)

`motor.AsyncIOMotorClient` is thread-safe and designed to be shared. Creating one per request would waste connection pool slots. Pattern mirrors `app.state.redis` already in use.

### D3: Idempotent collection + index creation on startup

`create_collection` with `check_exists=False` and `create_index` are idempotent when the collection/index already exist. Running this on every startup avoids a separate migration step and keeps the docker-compose dev loop frictionless.

### D4: Native time-series collection for `market_bars`

MongoDB 7 native time-series collections compress and bucket documents automatically, giving better storage and range-query performance than a standard collection with a manual index. `timeField="ts"` (UTC datetime), `metaField="metadata"` (sub-document with `symbol`, `interval`, `exchange`). Granularity set to `"seconds"`.

### D5: TTL index on `option_chains.captured_at` (30-day default)

Option chain snapshots older than 30 days have diminishing analytical value for intraday strategies. A TTL index auto-expires them, keeping the collection bounded. The TTL duration is read from `settings.MONGO_CHAIN_TTL_DAYS` (default 30) so it can be overridden without code changes.

### D6: New package `src/pdp/mongo/` (not mixed into existing modules)

Keeps Mongo concerns isolated. `client.py` owns connect/disconnect. `collections.py` exposes typed accessors (`get_bars_collection`, `get_chains_collection`). Future modules (bar writer, chain ingest) import from here without touching `main.py`.

## Risks / Trade-offs

- **Risk: Mongo unreachable at startup fails the app** → Mitigation: `/readyz` reports `mongo: "error"` but we intentionally let startup fail loudly (same policy as Postgres) so ops knows immediately rather than silently dropping data.
- **Risk: Time-series collection can't be converted to regular later** → MongoDB time-series collections are immutable in type; dropping and recreating would lose data. Mitigation: this is acceptable — we are designing for Mongo-as-warehouse from day one.
- **Risk: Native TS collection granularity mismatch** → Setting `granularity="seconds"` covers 1s to 1-day bars. Sub-second ticks are not stored here (Redis LTP cache handles live ticks).
- **Trade-off: No auth in dev** → `MONGO_URI=mongodb://localhost:27017` by default. Production operators must supply a URI with credentials via env. This is acceptable for a local-dev-first stack.

## Migration Plan

1. `docker compose pull mongo` / `docker compose up mongo -d`
2. `uv add motor`
3. Deploy code: app startup creates collections automatically (idempotent)
4. Rollback: remove `mongo` from lifespan + `docker compose stop mongo` — no data loss risk since no writes yet

## Open Questions

- Should `market_bars` expireAfterSeconds also be set, or keep bars forever? — **Decision: no TTL on bars** (they are the analytical record of truth; storage is cheap in Mongo).
- Should we enable Mongo authentication even in docker-compose dev? — **Decision: no for now**, follow-on infra change.
