# strangle-leg-state-durability

## Why

A strangle leg's *type* — short, protective hedge, or momentum long — determines the direction of the
order that closes it. That type is held only in Python memory, in which of three lists the `OpenLeg`
object sits. It does not survive a restart, and the code that claims to restore it reads a collection
nothing ever writes.

`_rehydrate_legs` (`backend/pdp/strategies/directional_strangle.py:1772`) rebuilds the leg lists from
PostgreSQL `Position` rows on startup. `Position` has **no leg-type column** (`pdp/orders/models.py:100`).
So to classify each restored leg it queries Mongo:

```python
from pdp.mongo.collections import get_events_collection   # :1812
col = get_events_collection(self.ctx._mongo_db)            # :1815
cursor = col.find({"event_type": "leg_open", "strategy_id": ..., "sid": {"$in": ...}})  # :1816
```

`get_events_collection` has exactly two callers in the repository — `directional_strangle.py:1815`
and `strategy/routes.py:332` — and **both are reads**. `_emit_event` writes to structlog, a JSONL
file, OpenSearch and an in-memory `_activity` deque. It has never written to Mongo. `leg_open_by_sid`
is therefore always `{}`, and every rehydrated leg is silently classified as a short.

The consequence on 2026-07-09 was a genuinely *long* SENSEX hedge (sid 822169) restored as a short.
`_close_short_leg` then placed a BUY to "close" it. Because the real position was long, the BUY grew
it: 4 → 8 → 16 lots across three uncommanded restarts. Each restart came from a `uvicorn --reload`
watcher (see `dev-reload-scoping`), so the bug fired three times in one session.

`f045282` patched the *symptom*: `_close_short_leg` (`:1359-1377`) now derives the closing side from
the broker's `net_qty` sign and fires `POSITION_SIZE_CAPPED` when the sign contradicts the assumed
type. That converts silent position growth into a correct close plus a loud alert — genuinely
valuable, and it must stay. But between rehydration and its next close event, a misclassified leg is
still wrong in memory: `state()` reports its P&L with the inverted sign convention, the console shows
a hedge as a short, `_close_matching_hedge` looks for a hedge that is filed as a short, and the
`take_profit` / `stop_half` / `stop_all` rules in `on_tick` (`:512-560`) — which apply **only to
`_short_legs`** — begin evaluating exit conditions against a long hedge.

Three further durability gaps sit in the same area:

- **`_rehydrate_legs` cannot restore `is_hedge` even in principle**, because the strategy never
  persists it. The fix is not a better Mongo query; it is a column.
- **The idempotency guard is wrong for a partial restore.** `:1781` returns early when *any* leg list
  is non-empty. A rehydrate that raced a first tick would leave the remaining positions unadopted,
  invisible to `_close_all`, and unsquared at session end.
- **`Position` is keyed by `(strategy_id, security_id)`**, so a strike that is closed and reopened
  within a day reuses the row. Nothing records that the leg's identity changed, which is what makes
  `entry_price` and `avg_price` re-basing (already fixed under `execution-console-daily-parity`)
  fragile to revisit.

## What Changes

- **Persist the leg type in PostgreSQL.** Add `leg_kind` (`short` | `hedge` | `momentum`) and
  `opt_type`, `strike`, `expiry` to a durable store keyed by `(strategy_id, security_id)` — either as
  columns on `Position` or, preferably, a dedicated `strategy_leg` table so `Position` stays a pure
  broker-ledger mirror. Write it in the same transaction that opens the leg. A leg's type is decided
  once, at open, and never inferred again.

- **Rehydrate from the durable store alone.** `_rehydrate_legs` reads `leg_kind` from PostgreSQL and
  drops the Mongo lookup entirely. Delete the dead `get_events_collection` read at `:1812-1821`. A
  position with an open broker quantity and **no** durable leg row is an orphan: it is adopted, its
  type inferred from the `net_qty` sign, and a critical `LEG_TYPE_UNKNOWN` event is emitted naming it.

- **Make the idempotency guard total.** Rehydration either adopts every open `Position` for the
  strategy or raises. It runs before the strategy accepts its first tick, and the "already populated"
  early-return at `:1781` becomes an assertion that the lists are empty.

- **Keep the net-qty sign check as a safety net, and make it an alarm.** The `POSITION_SIZE_CAPPED`
  guard at `:1366` stays, but a sign contradiction after this change means the durable store is wrong
  — a far more serious condition than a misclassified rehydrate. It emits `LEG_TYPE_CONTRADICTED`
  and, in live mode, halts the strategy for that underlying rather than continuing to trade on state
  it knows is corrupt.

- **Prove the round trip.** A test opens one leg of each type, simulates a process restart by
  constructing a fresh strategy instance against the same database, and asserts all three legs are
  restored into the correct lists with the correct `opt_type`, `strike`, `lots` and `entry_price`.
  This is the test whose absence allowed a "rehydration" function that never rehydrated anything to
  ship.

## Impact

- **Affected specs:** `strangle-leg-state-durability` (new). Amends
  `openspec/specs/strategy-registry/spec.md`.
- **Affected code:** `backend/pdp/strategies/directional_strangle.py` (`_rehydrate_legs:1772`, the
  three `_open_*` methods, `_close_short_leg:1326`), `backend/pdp/orders/models.py` (new
  `strategy_leg` table or `Position` columns), `backend/alembic/` (**migration required**),
  `backend/pdp/events/models.py` (`LEG_TYPE_UNKNOWN`, `LEG_TYPE_CONTRADICTED`),
  `backend/pdp/strategy/routes.py:332` (the other dead `get_events_collection` read — audit it).
- **Migration required.** This is the only change in the current sequence that alters the PostgreSQL
  schema. Existing open positions have no `leg_kind`; the backfill infers it from `net_qty` sign
  (negative ⇒ short, positive ⇒ hedge-or-momentum) and marks the ambiguity for operator review. Run
  the migration flat — outside market hours, with zero open positions — and the ambiguity disappears.
- **`execution-console-daily-parity` is already implemented** (all 23 tasks checked, unarchived). It
  fixed `entry_price=0`, the `avg_price` re-base, the DB-first ledger and the intraday broker poll.
  This change does **not** redo that work; it fixes the leg-*type* durability that change's
  `rehydrate_legs()` task left resting on a nonexistent Mongo write. Archive
  `execution-console-daily-parity` before or alongside this one.
- **Depends on `strangle-close-path-atomicity`.** That change collapses the three leg lists into a
  one-leg-per-security structure; `leg_kind` becomes a field on that structure rather than a list
  membership. Land it first, or this change writes a column for a data model that is about to change.
- **Paper-first.** Ties into [[leg_rehydration_misclassification_bug]], [[execution_daily_parity]],
  [[dead_command_channel_import]] — the last of which is the same class of defect: a subsystem that
  reads from something nothing writes, failing silently for weeks.
