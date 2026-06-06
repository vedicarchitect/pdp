## 1. Dependencies & Infrastructure

- [x] 1.1 Add `motor>=3.4` to `pyproject.toml` via `uv add motor`
- [x] 1.2 Add `mongo` service to `docker-compose.yml` (image `mongo:7`, port 27017, named volume `mongo_data`)

## 2. Settings

- [x] 2.1 Add `MONGO_URI: str = "mongodb://localhost:27017"` to `src/pdp/settings.py`
- [x] 2.2 Add `MONGO_DB_NAME: str = "pdp"` to `src/pdp/settings.py`
- [x] 2.3 Add `MONGO_CHAIN_TTL_DAYS: int = 30` to `src/pdp/settings.py`

## 3. Mongo Package

- [x] 3.1 Create `src/pdp/mongo/__init__.py` (empty)
- [x] 3.2 Create `src/pdp/mongo/client.py` — `connect(settings)` returns `(AsyncIOMotorClient, AsyncIOMotorDatabase)` and `disconnect(client)` closes it
- [x] 3.3 Create `src/pdp/mongo/collections.py` — `init_collections(db, settings)` async function that creates `market_bars` (time-series) and `option_chains` (with TTL index) idempotently; expose `get_bars_collection(db)` and `get_chains_collection(db)` accessors

## 4. App Wiring

- [x] 4.1 In `main.py` lifespan: call `connect()` on startup, store client + db on `app.state`, call `init_collections()`, call `disconnect()` on shutdown
- [x] 4.2 Update `/readyz` handler to ping MongoDB (`await db.command("ping")`) and include `"mongo": "ok"|"error"` in the response; return HTTP 503 if any dependency is unhealthy

## 5. Tests

- [x] 5.1 Unit test `init_collections()` with a mock db — assert `create_collection` and `create_index` are called with correct arguments
- [x] 5.2 Test `/readyz` with Mongo ping mocked as OK — assert `"mongo": "ok"` in response body
- [x] 5.3 Test `/readyz` with Mongo ping raising an exception — assert HTTP 503 and `"mongo": "error"`

## 6. Validation & Smoke

- [x] 6.1 Run `npx -y @fission-ai/openspec@latest validate --strict add-mongo-store`
- [x] 6.2 `docker compose up mongo -d` then `uv run pdp` — verify `/readyz` returns `{"status":"ready","db":"ok","redis":"ok","mongo":"ok"}`
- [x] 6.3 Connect to Mongo shell and confirm `pdp.market_bars` is a time-series collection and `pdp.option_chains` has the TTL index
