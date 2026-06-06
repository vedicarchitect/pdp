## Context

The `BarWriter` currently maintains a dedicated `asyncpg` connection and flushes closed bars via `COPY` into the `market_bars` TimescaleDB hypertable. The `/api/v1/bars` REST endpoint queries that same hypertable via SQLAlchemy. Phase 2 (`add-mongo-store`) has already provisioned a MongoDB 7 time-series collection `market_bars` (field `ts`, metadata field `metadata`) and wired `app.state.mongo_db` into the lifespan. This change re-routes writes and reads to Mongo and removes the Timescale dependency for bars.

## Goals / Non-Goals

**Goals:**
- Replace `asyncpg`-based `BarWriter` with a `motor`-based writer that inserts into the `market_bars` time-series collection
- Re-point `GET /api/v1/bars/{security_id}` to query MongoDB
- Drop the `market_bars` hypertable via Alembic migration 0008
- Remove `asyncpg` from dependencies if it is unused elsewhere after the migration

**Non-Goals:**
- Changing the `/api/v1/bars` response shape or query parameters
- Migrating historical bar data from Timescale to Mongo (start fresh; backfill is a separate concern)
- Removing the TimescaleDB Docker image (Postgres is still needed for the ledger)
- Modifying the `BarAggregator`, Redis fan-out, or WebSocket layer

## Decisions

### D1 — Document shape for `market_bars` time-series collection

MongoDB time-series documents need a `timeField` (`ts`) and a `metaField` (`metadata`). Each bar document:

```json
{
  "ts": "<bar_time as UTC datetime>",
  "metadata": { "security_id": "13", "timeframe": "5m" },
  "open": 1234.5, "high": 1240.0, "low": 1230.0, "close": 1238.0,
  "volume": 50000, "oi": 12000
}
```

`ts` and `metadata` are chosen to match the collection's declared `timeField`/`metaField`. Queries filter on `metadata.security_id` + `metadata.timeframe` and sort by `ts` — MongoDB time-series collections index `ts` automatically.

**Rationale:** Matches the collection definition already created in Phase 2 (`init_collections`). No schema change needed.

### D2 — BarWriter receives `motor.AsyncIOMotorCollection` at construction

Instead of a raw DSN, `BarWriter` is constructed with the motor collection object sourced from `app.state.mongo_db`. This is consistent with how other components receive their dependencies via lifespan.

**Rationale:** Avoids a second connection to Mongo from within the writer; the Phase 2 client is already managed by the lifespan and shared safely.

### D3 — Flush mechanism: `insert_many` replacing `COPY`

The existing flush loop (1s / 500 rows) is retained. Each flush calls `collection.insert_many(docs, ordered=False)` where `docs` are dicts shaped per D1. `ordered=False` allows partial batch success and skips duplicate-key errors without aborting the whole batch.

**Rationale:** `insert_many` is the idiomatic motor batch write. `ordered=False` mirrors the existing silent-skip behaviour for duplicate bars.

### D4 — `/api/v1/bars` query uses `find()` with sort + limit

```python
cursor = collection.find(
    {"metadata.security_id": security_id, "metadata.timeframe": tf.value},
    sort=[("ts", -1)],
    limit=limit,
)
```

Returns documents newest-first, mirroring the existing TimescaleDB `ORDER BY bar_time DESC LIMIT n` behaviour.

**Rationale:** Direct 1:1 replacement of the SQL query; no aggregation pipeline needed for this read pattern.

### D5 — `asyncpg` removal

After removing `BarWriter`'s asyncpg import, check if any other module imports `asyncpg`. If none do, run `uv remove asyncpg`. The `MarketBar` SQLAlchemy model and its table can also be removed since nothing will query it.

### D6 — Migration 0008 drops hypertable

Alembic migration `0008_drop_market_bars.py` runs `DROP TABLE IF EXISTS market_bars CASCADE`. TimescaleDB will automatically remove the associated chunks and compression/retention policies when the parent table is dropped.

**Rollback:** No automated rollback — data in Timescale is dropped permanently. Acceptable because (a) we start fresh from Mongo, (b) this is a dev-only platform for now.

## Risks / Trade-offs

- **Data loss on rollback** → Mitigation: there is no live production data; migration is one-way by design.
- **Time-series collection query performance on large datasets** → Mitigation: MongoDB time-series auto-indexes on `ts`; compound index on `{metadata: 1, ts: -1}` added by `init_collections` in Phase 2 covers the filter + sort pattern.
- **`ordered=False` insert_many swallows errors silently** → Mitigation: log a warning with the count of write errors from the `BulkWriteError.details` so data loss is observable.

## Migration Plan

1. Apply migration 0008 (`alembic upgrade head`) — drops `market_bars` hypertable.
2. Deploy new `BarWriter` + updated `/api/v1/bars` route.
3. Verify `/readyz` shows `"mongo": "ok"`.
4. Confirm bars appear in `pdp.market_bars` after the next tick flush.
5. Run `uv remove asyncpg` if no remaining imports exist.

## Open Questions

- None — all decisions resolved above.
