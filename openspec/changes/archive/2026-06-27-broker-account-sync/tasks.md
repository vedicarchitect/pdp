## 1. Settings + Mongo collection
- [x] 1.1 Added `BROKER_SYNC_ENABLED`, `BROKER_SYNC_EOD_TIME="15:45"`, `BROKER_ACCOUNT_LABEL` to `pdp/settings.py`
- [x] 1.2 Registered `broker_snapshots` + unique/read indexes + `get_broker_snapshots_collection` in `pdp/mongo/collections.py`

## 2. PG models + migration
- [x] 2.1 `pdp/broker_sync/models.py`: `BrokerHolding`, `BrokerPosition`, `BrokerFund`, `BrokerSyncRun`
- [x] 2.2 Alembic `0013_broker_sync_tables.py` (+ env.py model import)
- [x] 2.3 `task db:migrate` applied (0012 → 0013)

## 3. Read-only Dhan account client
- [x] 3.1 `pdp/broker_sync/client.py` `BrokerAccountClient` — async read methods, SDK calls via `asyncio.to_thread`
- [x] 3.2 Envelope unwrap + `BrokerSyncError` on failure; `_as_rows` normalizes list/dict/None

## 4. Snapshots + service
- [x] 4.1 `pdp/broker_sync/snapshots.py` `upsert_snapshot` (idempotent by key) + `get_snapshot`
- [x] 4.2 `BrokerSyncService.run_daily` — run-row lifecycle, per-report catch, ok/partial/skipped
- [x] 4.3 `_replace_state_and_reconcile` — delete-by-account + insert in one transaction
- [x] 4.4 `_reconcile` — diff vs internal `positions`; `broker_recon_mismatch` log; summary on run

## 5. Scheduler + routes + main wiring
- [x] 5.1 `pdp/broker_sync/scheduler.py` EOD loop (IST), skip-if-already-ok
- [x] 5.2 `pdp/broker_sync/routes.py` `/api/v1/broker-sync` (run / runs / runs/{id} / holdings / positions / funds)
- [x] 5.3 `pdp/main.py` — router included + scheduler started in lifespan when enabled
- [x] 5.4 `pdp/broker_sync/CLAUDE.md`

## 6. Historical backfill
- [x] 6.1 `pdp/broker_sync/backfill.py` — trade_history + ledger → per-day docs (bucketed by row date)
- [x] 6.2 `scripts/broker_sync.py` CLI (daily + `--from/--to` backfill)

## 7. Taskfile
- [x] 7.1 `task broker:sync` + `task broker:backfill` (dir: backend)

## 8. Tests
- [x] 8.1 `tests/broker_sync/test_service.py` — ok / skipped / partial / reconcile-mismatch (DB-backed)
- [x] 8.2 `tests/broker_sync/test_snapshots.py` — upsert idempotency + backfill bucketing
- [x] 8.3 Reconcile mismatch covered in `test_service.py`; client envelope in `test_client.py`
- [x] 8.4 `uv run pytest tests/broker_sync` → 12 passed

## 9. Validation
- [x] 9.1 `openspec validate -- broker-account-sync --strict` (valid)
- [x] 9.2 With live creds (owner-run): set `BROKER_SYNC_ENABLED=true`, `task broker:sync` → verify `broker_snapshots` docs + PG mirror + run row
