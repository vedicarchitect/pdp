# broker_sync/ — Daily Dhan account archival

Stores the **broker's view** (Dhan = source of truth): immutable daily snapshots in MongoDB +
a current-state mirror in PostgreSQL. Read-only (no orders). Chunk 2 of the program.

## Minimal context (load only these)
`models.py`, `service.py`, `client.py`, `snapshots.py` — plus `pdp/mongo/collections.py`
(broker_snapshots), `pdp/orders/dhan_broker.py` (client bootstrapping), `pdp/orders/models.py`
(Position, for reconciliation).

## Files
| File | Role |
|------|------|
| `client.py` | `BrokerAccountClient` — async, read-only Dhan reports (holdings/positions/funds/orders/trades/trade_history/ledger) |
| `models.py` | PG current-state: `BrokerHolding`, `BrokerPosition`, `BrokerFund`, `BrokerSyncRun` (audit) |
| `snapshots.py` | Mongo `broker_snapshots` upsert — one doc per (account_id, date, report_type) |
| `service.py` | `BrokerSyncService` — `refresh_state` (intraday) + `run_daily` (EOD archival) |
| `scheduler.py` | `BrokerSyncScheduler` — EOD loop at `BROKER_SYNC_EOD_TIME` IST (default 15:45) |
| `intraday_poller.py` | `BrokerIntradayPoller` — market-hours `refresh_state` every `BROKER_INTRADAY_POLL_SECONDS` |
| `routes.py` | `/api/v1/broker-sync` — status/run/runs/holdings/positions/funds |
| `backfill.py` | `backfill_history` — one-time trade_history + ledger over a date range |

## The two entry points

| | `refresh_state` (intraday) | `run_daily` (EOD) |
|---|---|---|
| Fetches | holdings, positions, funds | + orders, trades, ledger |
| PG mirror | replaced | replaced |
| Mongo snapshot | **no** | yes |
| `BrokerSyncRun` row | **no** | yes |
| Reconcile | **no** | live mode only |

The poller must never call `run_daily`: its run row would satisfy `already_succeeded` and
silently cancel the 15:45 archival, and its snapshot would overwrite the day's EOD state with a
mid-session view.

## Conventions
- Idempotent by `(account_id, snapshot_date, report_type)`; re-running a date overwrites.
- Credential-gated: no creds ⇒ run recorded `skipped`, never crashes.
- Mongo = immutable history (truth); PG mirror is rebuilt each run (can't drift).
- `already_succeeded` counts only `auto`/`manual` triggers.
- Reconcile runs only when `LIVE` and `BROKER == "dhan"`. Paper `Position` rows come from
  `PaperBroker` and have no broker counterpart, so every one would mismatch. Read-only always.
- `snapshot_date` defaults to the **IST** calendar date (`ist_today()`).
- Everything keyed by `account_id` for future multi-broker/Kite (chunk 15).
- Holdings/positions/funds are point-in-time → cannot be backfilled (only go-forward).
- `GET /status` is how you tell *disabled* / *no credentials* / *never synced* / *flat account*
  apart; the list endpoints 503 when the subsystem is off. `last_state_refresh_at` (not
  `last_run`) is the mirror-freshness signal, since the intraday path writes no run row.

## Run
`task broker:sync -- [--date YYYY-MM-DD]` · `task broker:backfill -- --from YYYY-MM-DD [--to ...]`
