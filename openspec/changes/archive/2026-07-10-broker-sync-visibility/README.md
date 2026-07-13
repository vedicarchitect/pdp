# broker-sync-visibility — minimal context

Read only these to work this change.

## Backend
| File | Why |
|------|-----|
| `backend/pdp/broker_sync/service.py` | `run_daily`, `_replace_state_and_reconcile`, `_reconcile`, `already_succeeded` — the split lands here |
| `backend/pdp/broker_sync/intraday_poller.py` | Calls the full `run_daily`; must call `refresh_state` |
| `backend/pdp/broker_sync/scheduler.py` | EOD loop; its `already_succeeded` guard is what the poller pre-empts |
| `backend/pdp/broker_sync/eod_reconcile.py` | Read-only comparison; needs the live-mode gate |
| `backend/pdp/broker_sync/routes.py` | `_service` guard exists but only `/run` uses it |
| `backend/pdp/broker_sync/schemas.py` | New `BrokerSyncStatusOut` |
| `backend/pdp/broker_sync/CLAUDE.md` | Conventions this change must keep (idempotency key, Mongo=truth) |
| `backend/pdp/settings.py` | `BROKER_SYNC_ENABLED:47`, `LIVE:35`, `BROKER:36` |
| `backend/pdp/runtime/groups.py` | Broker-sync wiring at `:566-593` |
| `backend/pdp/main.py` | Lifespan swallows `group_start_failed` at `:37` |
| `backend/pdp/orders/paper.py` | `Position(...)` at `:426` — why paper rows reach reconcile |

## App
| File | Why |
|------|-----|
| `app/lib/features/manage/data/manage_repository.dart` | `:68` comment encodes the empty-200 assumption |
| `app/lib/features/manage/` | Four-state rendering |

## Key facts established during investigation
- Reconcile is **read-only**; it cannot corrupt the ledger (`eod_reconcile.py:10`).
- `BROKER_SYNC_ENABLED` is **absent from `backend/.env`**, so the `settings.py` default governs.
  (`OPTIONS_UNDERLYINGS`, by contrast, *is* set in `.env` — a code-only edit there is a no-op.)
- `.env` is not in git; verify post-deploy with `GET /api/v1/broker-sync/status`.
- Holdings/positions/funds are point-in-time and cannot be backfilled — only go-forward.

## Related
Blocks `strangle-close-path-atomicity` and `strangle-leg-state-durability`: reconcile is the only
check that would surface leg-accounting drift, so it must be trustworthy and quiet in paper mode
before those land.
