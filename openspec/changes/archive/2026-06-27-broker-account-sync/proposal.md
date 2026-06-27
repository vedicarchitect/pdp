## Why

PDP places and tracks its own orders in the internal ledger, but it does **not** persist what
the broker itself reports — holdings, positions, funds, orderbook, tradebook, and ledger. The
moment any of those change at Dhan, yesterday's truth is gone. The owner wants to **track
everything from the broker and keep every historical record** as the spine of complete account
management. This chunk is that spine: a daily, idempotent sync of the Dhan account into
permanent storage, plus a one-time historical pull of the transactional logs.

It deliberately stores the **broker's view** (Dhan as source of truth), kept separate from the
platform's internally-computed ledger, so the two can later be reconciled.

## What Changes

- **New `pdp/broker_sync/` module** with a read-only Dhan account client (reuses the existing
  `pdp/orders/dhan_broker.py` credential bootstrapping; uses `get_holdings`, `get_positions`,
  `get_fund_limits`, `get_order_list`, `get_trade_book`, `get_trade_history`, `ledger_report`).
- **Mongo immutable daily archive** — one collection `broker_snapshots`, one document per
  `(account_id, snapshot_date, report_type)`, idempotent by that key (mirrors the existing
  `portfolio_snapshots` daily-doc pattern). `report_type ∈ {holdings, positions, funds,
  orders, trades, ledger}`. Re-running a date overwrites its docs.
- **PG current-state tables** — `broker_holdings`, `broker_positions`, `broker_funds` (latest
  snapshot, replaced each sync) for fast queries/joins, plus a `broker_sync_run` audit table
  (run id, account, date, status, per-report counts, timing, error). One Alembic migration.
- **`BrokerSyncService`** — orchestrates a full daily sync: fetch all reports → write Mongo
  immutable docs → replace PG current-state → record the run. Light **reconciliation** against
  the internal `positions` table (flag/log mismatches).
- **Auto EOD + manual trigger** — a scheduled daily run after market close (~15:45 IST,
  configurable) wired into the app lifespan, plus REST endpoints under `/api/v1/broker-sync`
  (run now, status, list runs, read current holdings/positions/funds) and a `task` command.
- **One-time historical backfill** — a command that pulls `trade_history` + `ledger` over a
  chosen date range into the Mongo archive (Dhan only reports *current* holdings/positions, so
  those cannot be backfilled).
- **Settings** — `BROKER_SYNC_ENABLED`, `BROKER_SYNC_EOD_TIME` (default `15:45`), account
  label; Dhan creds reuse existing `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`.

## Capabilities

### New Capabilities
- `broker-account-sync`: daily idempotent archival of all Dhan-reported account state +
  transactional logs (Mongo history + PG current-state), auto-EOD + manual triggers, a
  one-time historical ledger/trade backfill, and basic reconciliation against the internal
  ledger.

## Impact

- **New** `backend/pdp/broker_sync/` (`client.py`, `models.py`, `snapshots.py`, `service.py`,
  `backfill.py`, `routes.py`, `scheduler.py`, `CLAUDE.md`).
- **New** Mongo collection `broker_snapshots` (registered in `pdp/mongo/collections.py`).
- **New** PG tables + one Alembic migration (`broker_holdings`, `broker_positions`,
  `broker_funds`, `broker_sync_run`).
- **Edit** `pdp/settings.py` (new keys), `pdp/main.py` (start scheduler + include router),
  `Taskfile.yml` (`broker:sync`, `broker:backfill`), `pdp/mongo/collections.py`.
- **Account scope**: single Dhan account now; every record is keyed by `account_id` so a
  second broker (Kite, chunk 15) and multi-account slot in without schema change.
- **Safety**: read-only Dhan calls (no orders); credential-gated — no creds ⇒ sync logs a
  skip, never crashes. Respects Dhan non-trading API rate limits (20/s).
- **Out of scope**: P&L statements / contract notes / charges files (chunk 3
  `broker-reports-vault`); the Flutter UI for this data (chunks 9/11/14).
