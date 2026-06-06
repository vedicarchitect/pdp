## 1. Database Migration

- [x] 1.1 Create `alembic/versions/0008_drop_market_bars.py` — `DROP TABLE IF EXISTS market_bars CASCADE` (drops hypertable + TimescaleDB chunks/policies automatically)

## 2. BarWriter Rewrite

- [x] 2.1 Rewrite `src/pdp/market/bar_writer.py` — constructor accepts `motor.AsyncIOMotorCollection` instead of a DSN string; remove `asyncpg` import
- [x] 2.2 Replace `_flush()` method: build list of dicts `{"ts": bar.bar_time, "metadata": {"security_id": bar.security_id, "timeframe": bar.timeframe}, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "oi": ...}` and call `collection.insert_many(docs, ordered=False)`
- [x] 2.3 On `BulkWriteError` in `_flush()`: log a warning with `details["nInserted"]` and `details["writeErrors"]` count; do not re-queue (duplicates are permanent)
- [x] 2.4 Remove `start()` / `stop()` asyncpg connection management — motor collection is already connected; simplify flush loop to not open/close a connection

## 3. REST Endpoint Update

- [x] 3.1 Update `GET /api/v1/bars/{security_id}` in `src/pdp/market/routes.py` — replace SQLAlchemy `select(MarketBar)` with `request.app.state.mongo_db["market_bars"].find({"metadata.security_id": security_id, "metadata.timeframe": tf.value}, sort=[("ts", -1)], limit=limit)`
- [x] 3.2 Update the response serialisation — read `doc["ts"].isoformat()` for `bar_time` and `doc["open"]` etc. directly from the Mongo document; remove `Depends(get_db)` from this endpoint if it is no longer needed
- [x] 3.3 Remove `from pdp.market.bar_model import MarketBar` import from `routes.py` (no longer queried)

## 4. App Wiring

- [x] 4.1 Update `src/pdp/main.py` lifespan — pass `app.state.mongo_db["market_bars"]` (the collection) to `BarWriter` constructor instead of the Postgres DSN
- [x] 4.2 Delete `src/pdp/market/bar_model.py` (the `MarketBar` SQLAlchemy model) — no longer needed after removing TimescaleDB query

## 5. Dependency Cleanup

- [x] 5.1 Check all project files for `import asyncpg` or `asyncpg` references; direct BarWriter usage removed — asyncpg retained as an indirect SQLAlchemy async dialect dependency (`postgresql+asyncpg://` URL)

## 6. Tests

- [x] 6.1 Update `tests/market/test_bar_writer.py` — replace asyncpg mock with a mock motor collection; assert `insert_many` is called with correctly shaped documents
- [x] 6.2 Update `tests/market/test_bars_route.py` — replace `db` session fixture with a mock `mongo_db` on `app.state`; assert `find()` is called with correct filter and the response serialises correctly
- [x] 6.3 Run full test suite (`pytest -q`) — all tests pass

## 7. Validation & Smoke

- [x] 7.1 Run `npx -y @fission-ai/openspec@latest validate --strict migrate-bars-to-mongo`
- [ ] 7.2 `docker compose up mongo -d && alembic upgrade head` — confirm migration 0008 runs without error and `market_bars` table no longer exists in Postgres
- [ ] 7.3 Start the app and check `/readyz` returns `{"status":"ready","db":"ok","redis":"ok","mongo":"ok"}` [requires live infra]
- [ ] 7.4 Trigger a bar close (via the market feed or a test tick) and confirm a document appears in `db.market_bars` via `mongosh` [requires live infra]
- [ ] 7.5 `GET /api/v1/bars/<security_id>?tf=5m` returns bars from MongoDB (not empty, correct shape) [requires live infra]
