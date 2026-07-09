# api-reliability-hardening

## Why

A full FastAPI + PostgreSQL + MongoDB review of `backend/pdp/` plus a whole-backend
correctness finder pass surfaced a cluster of production-reliability defects. They fall into
three buckets, all of which make the API unsafe or "stale and prone to dying":

1. **Security / input validation gaps** — every mutating route (kill-switch, reset-paper,
   order place/cancel, strategy start/stop, broker-sync, alerts) is reachable with **no
   authentication**; `OrderRequest.qty` has no `Field(gt=0)` and `_check_lot_freeze` lets
   `qty <= 0` through (`0 % n == 0`); journal `update_metadata` parses a raw `request.json()`
   with no schema; several list endpoints take unbounded `limit`; the legacy
   `backtest/routes.py` handlers declare `session: AsyncSession` with no `Depends(get_db)`, so
   every call 422s (live-reproduced).

2. **Money / data-correctness bugs** — a position **reversal through zero** books realized P&L
   but never resets `avg_price`, corrupting the unrealized MTM that feeds the hard-cap
   auto-kill (C1); editing journal metadata for a **past day** flushes an empty `trades: []`
   over the stored day, losing history (C2); duplicate live/paper fills can **double-book**
   because `_fill` has no idempotency guard (C3/C4); alert status is mutated on detached ORM
   objects and **never committed**, so alerts re-fire after restart and never re-arm (C6/C7);
   per-strategy "realized_pnl" is raw signed cash-flow, wrong for open/cross-day positions
   (C11).

3. **Resource / connection reliability** — the async SQLAlchemy engine has no
   `pool_recycle`/`pool_timeout` (idle connections closed by the DB go stale); the Motor client
   has no `socketTimeoutMS`/pool bounds (a stalled op hangs a coroutine forever); the options
   gap-backfill opens a fresh `pymongo.MongoClient` every cycle and never closes it (fd/thread
   leak, C8); `DhanTickerAdapter` blocks on a non-interruptible `sleep(30)` and `stop()` never
   cancels its task (shutdown hang, C10); the EOD snapshot only fires in a single `minute==36`
   window and silently skips a day on clock drift (C12).

All fixes are implemented as **generic, reusable, single-responsibility helpers** (shared
FastAPI dependencies, one Pydantic model per shape, one guard per invariant) — not duplicated
inline patches — per the project's standards directive.

## What Changes

- **New `backend/pdp/deps.py`** — shared FastAPI dependencies, each doing one task:
  `require_auth` (bearer/API-key `Security()` applied via router `dependencies=[...]` to all
  mutating routes), `PaginationParams` (`limit: int = Query(50, ge=1, le=500)`),
  `parse_ist_date()` (single guarded `date.fromisoformat` helper, `400` on malformed).
- **Typed request models with constraints** — `OrderRequest.qty: int = Field(gt=0)`; a
  `JournalMetadata` model replacing the raw `request.json()`; a belt-and-suspenders `qty > 0`
  guard in `_check_lot_freeze`.
- **Legacy backtest routes fixed or retired** — `backtest/routes.py` gets `Depends(get_db)`
  and its sync `engine.run()` moved off the loop via `run_in_threadpool`, or the router is
  removed in favour of the active `warehouse_routes.py`.
- **Idempotent fills** — `_fill` (paper + dhan) becomes a no-op when the order is already
  filled (single status guard), closing the double-book race.
- **Correct reversal cost-basis** — `upsert_position` resets `avg_price` to the new fill for
  the residual leg when an order flips the position sign.
- **Durable journal metadata edits** — metadata edits load the target day's stored trades
  before flush (no empty-`trades` overwrite).
- **Persistent alert lifecycle** — evaluator commits status transitions and re-arms on
  re-cross.
- **Accurate per-strategy realized P&L** — computed from matched round-trips, not raw
  cash-flow.
- **Bounded pools + lifecycle** — `pool_recycle`/`pool_timeout` on the PG engine; Motor
  `socketTimeoutMS`/`connectTimeoutMS`/`maxPoolSize`/`maxIdleTimeMS`; gap-backfill reuses a
  single client (`with MongoClient(...)`); `DhanTickerAdapter` uses an interruptible sleep and
  `stop()` cancels its task; EOD snapshot fires on a "not yet done today past 15:36" predicate,
  not an exact minute.

## Impact

- **Affected specs:** `api-hardening` (new — auth, validation, pools, lifecycle),
  `order-execution` (idempotent fills, qty guard), `paper-pnl-correctness` (reversal
  cost-basis), `paper-journal` (durable metadata edits), `alerts-ui` (persistent lifecycle).
- **Affected code:** `backend/pdp/deps.py` (new), `orders/routes.py`, `orders/router.py`,
  `orders/paper.py`, `orders/dhan_broker.py`, `journal/routes.py`, `journal/service.py`,
  `alerts/evaluator.py`, `risk/service.py`, `portfolio/service.py`, `backtest/routes.py`,
  `options/gap_backfill.py`, `market/dhan_ws.py`, `db/session.py`, `mongo/client.py`,
  and the mutating routes in `risk/routes.py`, `strategy/routes.py`, `broker_sync/routes.py`,
  `portfolio/routes.py`.
- **Reuses:** existing `get_db` dependency, `select_broker()` paper/live guard (already
  correct — unchanged), `EventService` for surfacing failures, `compute_daily_stats`. Adds no
  new external dependency.
- **Infra:** no AWS/Docker change (pool settings are env-tunable via existing `get_settings()`).
