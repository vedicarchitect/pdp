# broker-sync-visibility

## Why

Dhan holdings and manually-taken positions are invisible in the app, with no error shown.

The cause is a config gate, not a bug in the sync itself. `settings.py:47` defaults
`BROKER_SYNC_ENABLED = False` and the key is absent from `backend/.env`, so `runtime/groups.py:567`
never constructs `BrokerSyncService` and the PG mirror tables (`BrokerHolding`, `BrokerPosition`,
`BrokerFund`) stay empty forever. Meanwhile `main.py:144` registers `broker_sync_router`
*unconditionally*, and `routes.py:73/97/122` read those tables directly via `Depends(get_db)` — so
`/holdings`, `/positions` and `/funds` return an empty `Page` with **HTTP 200**. The Flutter side
already documents this as expected (`app/lib/features/manage/data/manage_repository.dart:68`:
"returns empty (not errors) when broker sync hasn't run"). A disabled subsystem and a genuinely
flat account are indistinguishable to every caller.

Simply flipping the flag is **not safe today**. The intraday poller and EOD reconcile shipped in
`f045282` and have never executed against a live Dhan account. Reading them end-to-end surfaces
four defects that only manifest once the flag is on:

1. **The intraday poller silently disables the EOD sync.** `scheduler.py:56` skips the 15:45 IST run
   when `already_succeeded(date_str)` is true. The poller calls the *full* `run_daily` every
   `BROKER_INTRADAY_POLL_SECONDS` (`intraday_poller.py:63`), each writing a `status=OK`
   `BrokerSyncRun` row for today's date. By 09:20 the EOD archival is permanently pre-empted.

2. **Reconcile alert-storms in paper mode.** `eod_reconcile.py:56` aggregates **all** PG `Position`
   rows with no mode filter. In paper mode those rows are written by `PaperBroker` (`paper.py:426`)
   and have no counterpart in the real Dhan account, so every open leg mismatches and emits a
   `POSITION_RECONCILE_MISMATCH` **critical** event — roughly 75 polls × N legs per session. The
   comparison is meaningless unless the platform is actually routing orders to Dhan.

3. **The poller performs a full daily archival, not a state refresh.** Each poll opens a
   `BrokerSyncRun` audit row, issues six Dhan calls (holdings, positions, funds, orders, trades,
   ledger), and `upsert_snapshot`s the day's Mongo document. That is ~450 API calls and ~75 audit
   rows per session, and it means the doc `broker_sync/CLAUDE.md` calls "immutable history (truth)"
   actually holds whatever the last poll saw, not the end-of-day state.

4. **Snapshot dates are stamped in UTC.** `service.py:119` uses `datetime.now(UTC)` while
   `scheduler.py:54` passes an IST date. The two agree during market hours and diverge for any run
   after 05:30 IST-equivalent rollover (e.g. a manual evening run lands on the previous day).

Reconcile itself is **read-only** and cannot corrupt the ledger — `eod_reconcile.py:10` states this
and both comparison paths only `select`. So the risk is noise and lost archival, not data loss.
This change lands broker sync on its own, ahead of the strategy and indicator fixes, so any
misbehaviour is cleanly attributable.

## What Changes

- **Enable broker sync by default.** `settings.py:47` → `BROKER_SYNC_ENABLED: bool = True`. The
  subsystem is already credential-gated (`service.py:122`: no creds ⇒ run recorded `skipped`, never
  raises) and the Dhan account client is read-only, so this places no orders.

- **Split state refresh from daily archival.** Add `BrokerSyncService.refresh_state()` — fetch
  holdings/positions/funds, replace the PG mirror, re-subscribe the market feed. No Mongo snapshot,
  no `BrokerSyncRun` row, no ledger/orders/trades fetch, no reconcile. `BrokerIntradayPoller` calls
  `refresh_state()` instead of `run_daily()`. Dhan calls per session drop from ~450 to ~225, audit
  rows from ~75 to 1, and the Mongo snapshot regains its EOD meaning.

- **Protect the EOD run.** `already_succeeded()` considers only `auto`/`manual` triggers, so no
  intraday activity can pre-empt the 15:45 archival.

- **Gate reconcile on live mode.** Both `_reconcile` and `reconcile_day_positions` run only when
  `LIVE and BROKER == "dhan"`. In paper mode the run records `recon: {"skipped": "paper_mode"}` —
  no critical events, no warning spam. This preserves the alert's meaning for the day it matters.

- **Make the endpoints tell the truth.** `/holdings`, `/positions` and `/funds` depend on the same
  `_service` guard as `/run`, returning **503 "broker sync not enabled"** rather than an empty 200.
  Add `GET /api/v1/broker-sync/status` → `{enabled, has_credentials, last_run}` so a caller can
  distinguish *disabled*, *no credentials*, *never ran*, and *genuinely zero rows*. Flutter's
  manage repository surfaces those four states instead of rendering an empty list.

- **Stamp snapshot dates in IST.** `service.py:119` uses the IST calendar date, matching
  `scheduler.py` and the project's IST convention.

- **Stop the lifespan from swallowing live-trading start failures.** `main.py:37` logs
  `group_start_failed` and continues for *every* group. Groups that carry live-trading
  responsibility re-raise, so a broken broker-sync or strategy wiring fails startup loudly instead
  of yielding a healthy-looking API with a dead subsystem — which is exactly how this defect stayed
  hidden.

## Impact

- **Affected specs:** `broker-sync-visibility` (new). No change to the archival schema, the
  idempotency key `(account_id, snapshot_date, report_type)`, or the "Mongo = truth, PG mirror
  rebuilt each run" contract — this change *restores* that contract.
- **Affected code:** `pdp/settings.py` (`BROKER_SYNC_ENABLED`), `pdp/broker_sync/service.py`
  (`refresh_state`, IST date, reconcile gate, `already_succeeded` trigger filter),
  `pdp/broker_sync/intraday_poller.py` (call `refresh_state`),
  `pdp/broker_sync/eod_reconcile.py` (live-mode guard), `pdp/broker_sync/routes.py` (503 guard +
  `/status`), `pdp/broker_sync/schemas.py` (`BrokerSyncStatusOut`), `pdp/main.py` (lifespan
  re-raise), `pdp/runtime/groups.py` (mark live-trading groups required),
  `app/lib/features/manage/` (four-state rendering), `backend/pdp/broker_sync/CLAUDE.md`.
- **No migration.** All four PG tables already exist; only their population changes.
- **`.env` is not in git.** `BROKER_SYNC_ENABLED` is absent from `backend/.env`, so the code default
  governs and no deployment-target edit is required. If a target *does* set it, that value wins —
  verify with `GET /api/v1/broker-sync/status` after deploy rather than assuming.
- **Prerequisite for the strategy work.** Reconcile is the only mechanism that would have caught
  the leg-accounting drift behind the 2026-07-09 inflated P&L. It has to be trustworthy — and
  quiet in paper mode — before `strangle-close-path-atomicity` and
  `strangle-leg-state-durability` land. Ties into [[live_backtest_parity]] and
  [[leg_rehydration_misclassification_bug]].
