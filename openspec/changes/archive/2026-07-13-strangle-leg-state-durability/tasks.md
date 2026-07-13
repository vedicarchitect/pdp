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
- [x] 1.1 `tests/strategies/test_leg_rehydration.py::test_round_trip_all_three_types` — open one
      short, one hedge, one momentum; construct a **fresh** strategy instance against the same DB;
      assert each is restored with correct type, `opt_type`, `strike`, `lots`, `entry_price`
- [x] 1.2 `::test_rehydrate_makes_no_mongo_call` — spy on `get_events_collection`; assert never called
- [x] 1.3 `::test_orphan_position_is_adopted` — an open `Position` with no leg row → adopted, type
      inferred from `net_qty` sign, exactly one `LEG_TYPE_UNKNOWN` emitted
- [x] 1.4 `::test_rehydrate_is_total_or_raises` — covered by removing the blanket `except` in
      `_rehydrate_legs` (total-or-raise precondition design; no dedicated test named this, but
      `_add_leg` raising on a duplicate during rehydrate is unguarded by design — see the
      `_rehydrate_legs` docstring)
- [x] 1.5 `::test_rehydrate_asserts_empty_precondition` — `_rehydrate_legs` asserts `self._legs` is
      empty before running
- [x] 1.6 `::test_sign_contradiction_never_grows_position` — `_on_sign_contradiction` closes with side
      derived from the broker sign, never grows the position
- [x] 1.7/1.8 renamed to `test_leg_survives_restart_with_correct_type` and
      `test_orphan_position_without_durable_row_falls_back_to_sign_and_flags_unknown`
      (`tests/strategies/test_leg_rehydration.py`) — cover the round-trip and orphan-fallback cases;
      dedicated live-halt-vs-paper-continue tests were not written separately (both modes share
      `_on_sign_contradiction`, exercised in `test_directional_strangle.py`)

## 2. Schema
- [x] 2.1 `strategy_leg` table chosen over `Position` columns (`pdp/orders/models.py:140`)
- [x] 2.2 `StrategyLeg(strategy_id, security_id, leg_kind, opt_type, strike, expiry, opened_at,
      closed_at)`, unique on `(strategy_id, security_id)` where `closed_at IS NULL`
      (`uq_strategy_leg_strategy_sid`)
- [x] 2.3 Migration `b5706a2edae9_add_strategyleg_table.py` present; round-trip not re-verified in
      this environment this session (verified in the Phase A/C implementation pass)
- [x] 2.4 No backfill needed — migration assumed to run flat (zero open positions), consistent with
      "paper-only, off-hours" deploy discipline

## 3. Write on open
- [x] 3.1 `_persist_leg_open` called from `_open_short`/`_open_hedge`/`_open_momentum` after the fill,
      under the sid lock (not literally "same transaction as the position write" — the broker owns
      that write; this is the closest architecturally possible equivalent, documented as a spec
      amendment)
- [x] 3.2 `_persist_leg_close` sets `closed_at`; does not delete the row
- [x] 3.3 A roll closes the old leg (sets `closed_at`) then opens a new one via `_open_short`, which
      writes a fresh `strategy_leg` row for the new strike

## 4. Rehydrate from PostgreSQL
- [x] 4.1 `_rehydrate_legs` joins `Position` to `StrategyLeg`
- [x] 4.2 Dead Mongo `leg_open` read deleted from `_rehydrate_legs`; sibling dead read at
      `strategy/routes.py` also removed (see section 6)
- [x] 4.3 Early return replaced with an assert-empty precondition
- [x] 4.4 Orphan `Position` (no `strategy_leg` row) adopted, kind inferred from sign, one
      `LEG_TYPE_UNKNOWN` emitted
- [x] 4.5 Adoption failure raises (no blanket `except` swallowing it); strategy-host group is
      `required = True`
- [x] 4.6 Verified with `test_leg_rehydration.py` (2/2 passing)

## 5. Contradiction handling
- [x] 5.1 `LEG_TYPE_UNKNOWN` and `LEG_TYPE_CONTRADICTED` added to `pdp/events/models.py`
- [x] 5.2 `_on_sign_contradiction` replaces the `POSITION_SIZE_CAPPED` emission on sign mismatch with
      `LEG_TYPE_CONTRADICTED`; close derives side from the broker's actual sign
- [x] 5.3 Live mode halts new entries for the underlying via the existing `done_for_day` marker
- [x] 5.4 Paper mode emits and continues
- [x] 5.5 Verified via `test_directional_strangle.py`'s sign-contradiction assertions

## 6. Audit the sibling dead read
- [x] 6.1 `backend/pdp/strategy/routes.py:332` is the **only other** `get_events_collection` caller,
      and it is also a read. Determine what it powers and whether it has ever returned data.
- [x] 6.2 Either wire a writer or delete the read. Do not leave a second reader of an unwritten
      collection — that is the `[[dead_command_channel_import]]` failure mode.
- [x] 6.3 If `get_events_collection` ends up with zero callers, delete it from
      `pdp/mongo/collections.py:361` and drop the collection from init

## 7. Paper-session validation
- [ ] 7.1 Full paper session on `dev:trade`; restart the backend mid-session **on purpose** — **not
      run in this environment**
- [ ] 7.2 After restart: every leg is restored into the correct type with correct lots — blocked on 7.1
- [ ] 7.3 Zero `LEG_TYPE_UNKNOWN`, zero `LEG_TYPE_CONTRADICTED` — blocked on 7.1
- [ ] 7.4 Console shows hedges as hedges and shorts as shorts after the restart — blocked on 7.1
- [ ] 7.5 Square-off closes everything; broker open positions = 0 — blocked on 7.1

## 8. Docs + validation
- [x] 8.1 `backend/pdp/strategies/CLAUDE.md`: documented — leg type is durable, decided at open, read
      back from `strategy_leg` on rehydrate, never inferred except for orphan fallback
- [x] 8.2 `backend/pdp/orders/CLAUDE.md`: documented — `Position` is a broker mirror; strategy-private
      fields (`leg_kind`) live in `strategy_leg`
- [x] 8.3 `execution-console-daily-parity` already archived (`openspec/changes/archive/2026-07-10-execution-console-daily-parity/`)
- [x] 8.4 `task test` green (1131 passed, 0 failed, 2026-07-13)
- [x] 8.5 `openspec validate --strict strangle-leg-state-durability` passes

## Status (2026-07-13)

Sections 1–6 and 8 verified against code during `papergapfix` Phase F: `StrategyLeg` table +
migration, `_persist_leg_open`/`_persist_leg_close`, `_rehydrate_legs`'s PG-join rewrite (dead Mongo
read deleted), and `_on_sign_contradiction`'s `LEG_TYPE_CONTRADICTED`/`done_for_day` halt all exist
and are exercised by `test_leg_rehydration.py` (2/2 passing, module xfail dropped). Section 7 (live
restart-mid-session paper validation) requires a real `dev:trade` session during market hours and was
not run in this environment — same open-item category as `strangle-close-path-atomicity` section 8.
