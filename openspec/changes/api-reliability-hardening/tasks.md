# Tasks — api-reliability-hardening

## 1. Shared reusable dependencies (`backend/pdp/deps.py`)
- [x] 1.1 Add `require_auth` (`APIKeyHeader` + `get_settings().API_AUTH_KEY`, 401 on mismatch)
- [x] 1.2 Add `PaginationParams` (`limit` 1..500, `offset` ≥0)
- [x] 1.3 Add `parse_ist_date()` (guarded `date.fromisoformat`, 400 on malformed, IST today default)
- [x] 1.4 Add settings keys: `API_AUTH_KEY`, `DB_POOL_RECYCLE_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`,
      `MONGO_SOCKET_TIMEOUT_MS`, `MONGO_CONNECT_TIMEOUT_MS`, `MONGO_MAX_POOL_SIZE`, `MONGO_MAX_IDLE_TIME_MS`

## 2. Apply auth to mutating routes (`dependencies=[Depends(require_auth)]`)
- [x] 2.1 `risk/routes.py` (`/kill`) + `housekeeping/routes.py` (reset-paper + all destructive
      tasks — was UNGUARDED, fixed 2026-07-09 verification pass)
- [x] 2.2 `orders/routes.py` (place/cancel)
- [x] 2.3 `strategy/routes.py` (start/stop/register), `broker_sync/routes.py` (run), `alerts/routes.py`

## 3. Request validation
- [x] 3.1 `OrderRequest.qty: int = Field(gt=0)`
- [x] 3.2 `_check_lot_freeze` belt-and-suspenders `if qty <= 0: reject`
- [x] 3.3 `JournalMetadata` model replaces raw `await request.json()` in `journal/routes.py`
- [x] 3.4 Journal + strangle-trades `date` params now route through `parse_ist_date`
      (400 on malformed instead of 500) — wired 2026-07-09

## 4. Legacy backtest routes (`backtest/routes.py`)
- [x] 4.1 Add `Depends(get_db)` to the 4 handlers (was 422 on every call)
- [x] 4.2 Move sync `engine.run()` off the loop via `run_in_threadpool`

## 5. Money / data correctness
- [x] **5. Race Conditions & Idempotency**
  - [x] 5.1. Add idempotency guard to `PaperBroker._fill` (status == FILLED)
  - [x] 5.2. Re-base `avg_price` in `upsert_position` on reversal to prevent skewed PnL
  - [x] 5.3. Hydrate `JournalService.update_metadata` memory state before flush (C2 fix)
  - [x] 5.4. Decouple `AlertEvaluator` notifications from async persistence logic (C6/C7 fixes)

## 6. Resource / connection reliability
- [x] **6. Database Connection Hardening**
  - [x] 6.1. Add `pool_recycle` / `pool_timeout` settings to `settings.py`
  - [x] 6.2. Apply recycle/timeout bindings in `db.session.get_engine()`
  - [x] 6.3. Add connection pool bounds (max size / timeouts) for `mongo.client`
  - [x] 6.4. Configure Motor driver timeout fallbacks to prevent background job stalls

## 7. Non-blocking handlers
- [x] **7. Resource Exhaustion & Rate Limits**
  - [x] 7.1. Bound pymongo connections in `gap_backfill.py` (maxPoolSize=1)
  - [x] 7.2. Ensure `DhanTickerAdapter._queue` enforces `put_nowait` with size limit
  - [x] 7.3. Handle `ProgrammingError` gracefully during `PaperBroker._load_open_orders` (degraded start)

## 8. Tests + validation
- [x] 8.1 Tests: require_auth (4), lot-freeze qty (4), parse_ist_date (3), paper-fill idempotency,
      journal-preserve, alert-rearm, db-pool-settings (`tests/test_api_hardening.py`)
- [x] 8.2 `task test` green for the hardening suite (`tests/test_api_hardening.py`, journal, orders)
- [~] 8.3 Env vars carry defaults + descriptions in `settings.py` (repo has no `.env.example`;
      config is sourced via `get_settings()` per project convention)
- [x] 8.4 `openspec validate --strict api-reliability-hardening` passes
