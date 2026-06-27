## Context

The platform owns an internal ledger (`orders`/`trades`/`positions` in PG) for orders it
places. The broker (Dhan) holds the authoritative account state — holdings, positions, funds,
orderbook, tradebook, ledger — which today is never persisted. We archive the broker's view
daily (immutable history) and keep a current-state mirror for fast reads + reconciliation,
following the established DB split (Mongo = history, PG = current/ACID).

Grounding patterns reused: `pdp/mongo/collections.py` daily-doc collections
(`portfolio_snapshots` keyed unique by date; `positional_eod_snapshots` keyed unique by date),
`pdp/orders/dhan_broker.py` Dhan client bootstrapping, `pdp/db/session.py` async sessions,
`pdp/jobs`/`pdp/housekeeping` for background work.

## Goals / Non-Goals

**Goals:** persist every Dhan-reported record daily, idempotently, keyed by `(account_id,
date, report_type)`; a current-state PG mirror; auto-EOD + manual trigger; one-time historical
backfill of the transactional logs; basic reconciliation vs the internal ledger.

**Non-Goals:** P&L statements / contract notes / charges (chunk 3); any Flutter UI (later);
multi-account/Kite (chunk 15, but schema is account-keyed now); modifying the internal ledger.

## Decisions

### D1: Mongo `broker_snapshots` — one regular collection, doc per (account, date, report_type)
Regular (not time-series) collection so it supports idempotent upsert. Unique index
`(account_id, snapshot_date, report_type)`. Document:
```
{ account_id, broker: "dhan", snapshot_date: "YYYY-MM-DD", report_type: "holdings",
  captured_at: <utc>, source: "dhan.get_holdings", count: N, data: [ ...raw normalized rows ] }
```
`report_type ∈ {holdings, positions, funds, orders, trades, ledger}`. For state reports
(holdings/positions/funds) the doc is that day's snapshot; for transactional reports
(orders/trades/ledger) it's that day's entries. Re-running a date upserts (overwrites) — safe.

### D2: PG current-state mirror (latest only) + run audit
`broker_holdings`, `broker_positions`, `broker_funds` hold only the **latest** sync, replaced
atomically each run (delete-by-account + insert within one transaction). Natural keys:
holdings `(account_id, security_id, isin)`, positions `(account_id, security_id,
exchange_segment, product_type)`, funds `(account_id)` single row. `broker_sync_run` is the
audit/idempotency log: `run_id` (uuid), `account_id`, `snapshot_date`, `trigger` (auto|manual),
`status` (running|ok|partial|failed|skipped), per-report counts (JSON), `started_at`,
`finished_at`, `error`. One Alembic migration adds all four.

### D3: `BrokerSyncService.run_daily(date, trigger)` orchestration
1. Insert a `broker_sync_run` row (status=running). 2. For each report: call the Dhan read
API, normalize, upsert the Mongo doc, accumulate counts; per-report failures are caught so one
bad report doesn't abort the rest (status becomes `partial`). 3. Replace PG current-state from
holdings/positions/funds. 4. Reconcile broker positions vs internal `positions` (log
`broker_recon_mismatch` per diff; store a summary on the run). 5. Finalize the run row.
No creds ⇒ status `skipped`, warn log, no crash.

### D4: Read-only Dhan account client
`pdp/broker_sync/client.py` wraps the dhanhq SDK read methods behind a small typed interface
(`fetch_holdings/positions/funds/orders/trades(date?)/trade_history(range)/ledger(range)`),
reusing the credential/bootstrapping approach from `dhan_broker.py`. Runs blocking SDK calls in
a thread (the codebase already bridges the sync SDK). Honors non-trading rate limits.

### D5: Scheduling — lifespan EOD loop + manual REST/task
`pdp/broker_sync/scheduler.py` runs an asyncio loop that fires once per trading day at
`BROKER_SYNC_EOD_TIME` IST (default 15:45), guarded by `broker_sync_run` (skip if today already
`ok`). Started in `main.py` lifespan when `BROKER_SYNC_ENABLED`. Manual: `POST
/api/v1/broker-sync/run` (optional `?date=`) and `task broker:sync`. Keeps the API stateless
per the cloud-readiness constraint — the loop is a separately-toggled concern.

### D6: Historical backfill (transactional logs only)
`pdp/broker_sync/backfill.py` + `task broker:backfill -- --from YYYY-MM-DD [--to]` iterates the
range pulling `trade_history` + `ledger` (paginated), writing per-day `broker_snapshots` docs.
Holdings/positions/funds are point-in-time and **cannot** be backfilled (documented).

## Risks / Trade-offs
- **Intraday positions vanish after square-off** → EOD run at 15:45 captures the day before
  Dhan resets; document that pre-close runs see open positions, post-reset runs see none.
- **Dhan response shapes vary by endpoint** (skill gotcha) → normalize each report; store raw
  rows under `data` so nothing is lost even if a field is unmapped.
- **Token expiry / DH-902** → caught per-report; run marked `partial`/`failed` with the error,
  surfaced in status; never crashes the app.
- **PG mirror vs Mongo divergence** → Mongo is the immutable record of truth; PG mirror is
  derived and fully rebuilt each run, so it can't drift.

## Migration Plan
1. Add settings + Mongo collection registration (no data migration).
2. Alembic migration for the four PG tables.
3. Service + client + routes + scheduler; wire into `main.py`.
4. Backfill command. 5. Tests (mocked Dhan client). 6. Manual `task broker:sync` against the
real account for validation (owner has live creds).

## Open Questions
- None blocking. Ledger doc granularity (per-day vs per-entry) settled as **per-day docs** to
  match the snapshot key; individual entries live in the doc's `data` array.
