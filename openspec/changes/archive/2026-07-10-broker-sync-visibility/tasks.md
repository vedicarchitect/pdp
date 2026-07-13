# Tasks — broker-sync-visibility

## 1. Service: split state refresh from daily archival
- [x] 1.1 `service.py`: extract the holdings/positions/funds fetch + PG-mirror replace into
      `refresh_state() -> dict[str, int]`; no `BrokerSyncRun`, no `upsert_snapshot`, no reconcile
- [x] 1.2 `refresh_state` calls `subscribe_current_positions()` after the mirror is replaced
- [x] 1.3 `refresh_state` returns `{}` and logs `broker_refresh_skipped_no_creds` when creds absent
- [x] 1.4 `run_daily` reuses the same mirror-replace helper (single implementation, no duplication)
- [x] 1.5 `intraday_poller.py:63`: call `self._service.refresh_state()` instead of `run_daily(...)`
- [x] 1.6 Delete the now-unused `trigger="intraday_poll"` string and its `SyncTrigger` member if unreferenced

## 2. Protect the EOD archival
- [x] 2.1 `already_succeeded()`: filter to `BrokerSyncRun.trigger.in_((SyncTrigger.AUTO, SyncTrigger.MANUAL))`
- [x] 2.2 Unit: an intraday-origin row for today does not satisfy `already_succeeded`

## 3. Gate reconcile on live mode
- [x] 3.1 `service.py`: compute `live = settings.LIVE and settings.BROKER == "dhan"` once
- [x] 3.2 Skip `_reconcile` and `reconcile_day_positions` when not `live`; set
      `recon = {"skipped": "paper_mode"}`
- [x] 3.3 `eod_reconcile.py`: docstring records the live-mode precondition; keep it read-only
- [x] 3.4 Unit: paper mode with open `Position` rows and an empty broker emits zero
      `POSITION_RECONCILE_MISMATCH` events
- [x] 3.5 Unit: live mode with a net-qty delta emits exactly one event per security and mutates no `Position`

## 4. IST snapshot date
- [x] 4.1 `service.py:119`: derive the default `snapshot_date` from `ZoneInfo("Asia/Kolkata")`
- [x] 4.2 `routes.py:41`: correct the `date` query-param description (says "defaults to today (UTC)")
- [x] 4.3 Unit: 19:30 UTC on 2026-07-09 → snapshot date `2026-07-10`

## 5. Endpoints tell the truth
- [x] 5.1 `routes.py`: `/holdings`, `/positions`, `/funds` take `Depends(_service)` so they 503 when disabled
- [x] 5.2 `schemas.py`: add `BrokerSyncStatusOut{enabled, has_credentials, last_run: BrokerSyncRunOut | None}`
- [x] 5.3 `routes.py`: add `GET /api/v1/broker-sync/status` (no auth beyond existing convention)
- [x] 5.4 API test: disabled → 503 on all three read endpoints; enabled+never-run → 200 empty + status shows null last run

## 6. Startup fails loudly for live-trading groups
- [x] 6.1 `runtime/groups.py`: add a `required: bool` class attribute; mark broker-sync, market-feed,
      strategy-host and order-routing groups `required = True`
- [x] 6.2 `main.py:37`: re-raise when `group.required`, otherwise keep fault-isolated logging
- [x] 6.3 Unit: a raising required group aborts lifespan; a raising optional group does not

## 7. Enable + app surface
- [x] 7.1 `settings.py:47`: `BROKER_SYNC_ENABLED: bool = True`
- [x] 7.2 `app/lib/features/manage/data/manage_repository.dart`: handle 503 distinctly; drop the
      stale "returns empty (not errors)" comment at `:68`
- [x] 7.3 `app/lib/features/manage/`: render four states — disabled, no credentials, never run, empty account
- [x] 7.4 `cd app && flutter analyze && flutter test` green

## 8. Docs + validation
- [x] 8.1 `backend/pdp/broker_sync/CLAUDE.md`: document `refresh_state` vs `run_daily`, the live-mode
      reconcile gate, and the IST snapshot date
- [x] 8.2 `docs/RUNBOOK.md`: how to verify broker sync after deploy (`GET /api/v1/broker-sync/status`)
- [x] 8.3 `task test` green (note: suite carries pre-existing failures — compare against baseline)
- [x] 8.4 `openspec validate --strict broker-sync-visibility` passes

## 9. Deploy-day verification (live, requires market hours)
- [ ] 9.1 App start with credentials: `GET /status` reports `enabled: true, has_credentials: true`
- [ ] 9.2 After one poll interval: `/holdings` and `/positions` show the real Dhan account
- [ ] 9.3 Over a full session: exactly one `BrokerSyncRun` row (the 15:45 `auto` run), zero
      `POSITION_RECONCILE_MISMATCH` events while in paper mode
- [ ] 9.4 `broker_snapshots` for the date holds the EOD state, not a mid-session poll
