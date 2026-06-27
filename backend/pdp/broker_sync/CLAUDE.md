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
| `service.py` | `BrokerSyncService.run_daily` — fetch → archive → replace PG mirror → reconcile → finalize |
| `scheduler.py` | `BrokerSyncScheduler` — EOD loop at `BROKER_SYNC_EOD_TIME` IST (default 15:45) |
| `routes.py` | `/api/v1/broker-sync` — run/runs/holdings/positions/funds |
| `backfill.py` | `backfill_history` — one-time trade_history + ledger over a date range |

## Conventions
- Idempotent by `(account_id, snapshot_date, report_type)`; re-running a date overwrites.
- Credential-gated: no creds ⇒ run recorded `skipped`, never crashes.
- Mongo = immutable history (truth); PG mirror is rebuilt each run (can't drift).
- Everything keyed by `account_id` for future multi-broker/Kite (chunk 15).
- Holdings/positions/funds are point-in-time → cannot be backfilled (only go-forward).

## Run
`task broker:sync -- [--date YYYY-MM-DD]` · `task broker:backfill -- --from YYYY-MM-DD [--to ...]`
