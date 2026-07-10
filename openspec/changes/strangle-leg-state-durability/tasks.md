# Tasks — strangle-leg-state-durability

> **Prerequisite:** `strangle-close-path-atomicity`. That change replaces the three leg lists with a
> one-leg-per-security structure; `leg_kind` becomes a field on it. Landing this first means writing a
> schema for a data model that is about to change.
>
> **This is the only change in the sequence with a PostgreSQL migration.** Run it flat: outside
> market hours, with zero open positions.
>
> **Paper-only.** Do not set `LIVE=1` at any point.

## 1. Tests first (they fail on today's code)
- [ ] 1.1 `tests/strategies/test_leg_rehydration.py::test_round_trip_all_three_types` — open one
      short, one hedge, one momentum; construct a **fresh** strategy instance against the same DB;
      assert each is restored with correct type, `opt_type`, `strike`, `lots`, `entry_price`
- [ ] 1.2 `::test_rehydrate_makes_no_mongo_call` — spy on `get_events_collection`; assert never called
- [ ] 1.3 `::test_orphan_position_is_adopted` — an open `Position` with no leg row → adopted, type
      inferred from `net_qty` sign, exactly one `LEG_TYPE_UNKNOWN` emitted
- [ ] 1.4 `::test_rehydrate_is_total_or_raises` — make adoption of the second of three positions fail
      → raises; the strategy processes no ticks
- [ ] 1.5 `::test_rehydrate_asserts_empty_precondition` — invoking with a non-empty structure raises
- [ ] 1.6 `::test_sign_contradiction_never_grows_position` — leg persisted `short`, broker `net_qty`
      positive → close order is `SELL`, resulting `abs(net_qty)` strictly decreases,
      `LEG_TYPE_CONTRADICTED` emitted
- [ ] 1.7 `::test_live_contradiction_halts_underlying` — `LIVE=1` + contradiction → no new leg opens
      for that underlying for the session
- [ ] 1.8 `::test_paper_contradiction_continues` — paper mode → event emitted, session continues

## 2. Schema
- [ ] 2.1 Decide: columns on `Position` vs a dedicated `strategy_leg` table.
      **Prefer `strategy_leg`** — `Position` is a broker-ledger mirror (`pdp/orders/models.py:100`)
      and `broker_sync` reconcile compares it against the broker. Strategy-private fields do not
      belong there.
- [ ] 2.2 `strategy_leg(strategy_id, security_id, leg_kind, opt_type, strike, expiry, opened_at,
      closed_at)`, unique on `(strategy_id, security_id)` where `closed_at IS NULL`
- [ ] 2.3 Alembic migration; verify `alembic upgrade head` then `downgrade -1` round-trips cleanly
- [ ] 2.4 Backfill for existing open positions: infer from `net_qty` sign, mark ambiguous rows for
      operator review. If the migration runs flat (zero open positions), the backfill is a no-op —
      **prefer that**.

## 3. Write on open
- [ ] 3.1 `_open_short` / `_open_hedge` / `_open_momentum`: insert the `strategy_leg` row in the same
      transaction that records the position
- [ ] 3.2 A close sets `closed_at`; it does not delete the row (the history is the audit trail)
- [ ] 3.3 Verify a roll writes a new row for the new strike rather than mutating the old one

## 4. Rehydrate from PostgreSQL
- [ ] 4.1 `directional_strangle.py:1772` — `_rehydrate_legs` joins `Position` to `strategy_leg`
- [ ] 4.2 **Delete `:1809-1821`** — the `get_events_collection` import, the `_mongo_db` `hasattr`
      probe, and the `leg_open` query. It has never returned a row.
- [ ] 4.3 Replace the early return at `:1781` with an assertion that the leg structure is empty
- [ ] 4.4 An open `Position` with no `strategy_leg` row → adopt, infer from sign, emit `LEG_TYPE_UNKNOWN`
- [ ] 4.5 Any adoption failure raises; the strategy host must not deliver ticks (verify the
      strategy-host group is `required = True` so lifespan re-raises — landed in `broker-sync-visibility`)
- [ ] 4.6 Verify with 1.1–1.5

## 5. Contradiction handling
- [ ] 5.1 Add `LEG_TYPE_UNKNOWN` and `LEG_TYPE_CONTRADICTED` to `pdp/events/models.py`
- [ ] 5.2 `_close_short_leg:1359-1377`: keep the net-qty sign derivation; replace the
      `POSITION_SIZE_CAPPED` emission with `LEG_TYPE_CONTRADICTED` (the cap event now means something
      else). Assert the resulting `abs(net_qty)` strictly decreases.
- [ ] 5.3 Live mode: halt new entries for that underlying for the session. Reuse the existing
      `done_for_day` halt marker rather than inventing a second mechanism.
- [ ] 5.4 Paper mode: emit and continue
- [ ] 5.5 Verify with 1.6–1.8

## 6. Audit the sibling dead read
- [ ] 6.1 `backend/pdp/strategy/routes.py:332` is the **only other** `get_events_collection` caller,
      and it is also a read. Determine what it powers and whether it has ever returned data.
- [ ] 6.2 Either wire a writer or delete the read. Do not leave a second reader of an unwritten
      collection — that is the `[[dead_command_channel_import]]` failure mode.
- [ ] 6.3 If `get_events_collection` ends up with zero callers, delete it from
      `pdp/mongo/collections.py:361` and drop the collection from init

## 7. Paper-session validation
- [ ] 7.1 Full paper session on `dev:trade`; restart the backend mid-session **on purpose**
- [ ] 7.2 After restart: every leg is restored into the correct type with correct lots
- [ ] 7.3 Zero `LEG_TYPE_UNKNOWN`, zero `LEG_TYPE_CONTRADICTED`
- [ ] 7.4 Console shows hedges as hedges and shorts as shorts after the restart
- [ ] 7.5 Square-off closes everything; broker open positions = 0

## 8. Docs + validation
- [ ] 8.1 `backend/pdp/strategies/CLAUDE.md`: leg type is durable, decided at open, never inferred
- [ ] 8.2 `backend/pdp/orders/CLAUDE.md`: `Position` is a broker mirror — strategy-private fields
      live in `strategy_leg`
- [ ] 8.3 Archive `execution-console-daily-parity` (23/23 tasks done, unarchived) — its
      `rehydrate_legs()` task rested on this bug
- [ ] 8.4 `task test` green against the recorded baseline
- [ ] 8.5 `openspec validate --strict strangle-leg-state-durability` passes
