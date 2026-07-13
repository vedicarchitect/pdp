# Tasks — strangle-close-path-atomicity

> **Prerequisite:** `dev-reload-scoping`. Editing strategy code during a session currently restarts
> the backend and re-triggers the rehydration bug, corrupting every observation you make here.
>
> **All work is paper-only.** Do not set `LIVE=1` at any point in this change.

## 1. Reproduce before fixing — these tests must FAIL on today's code
- [x] 1.1 `tests/strategies/test_roll_atomicity.py::test_skipped_no_spot_leaves_position_open`
      — `_last_spot = None`, trigger a roll → assert the short leg is still in `_short_legs`, the
      matching hedge is still open, and **zero** orders were placed
- [x] 1.2 `::test_no_instrument_leaves_position_open` — `resolve_otm_option` returns `None` → same assertions
- [x] 1.3 `::test_low_premium_leaves_position_open` — new premium < `roll_target_min_prem` → same assertions
- [x] 1.4 `::test_concurrent_roll_runs_once` — `asyncio.gather` two `on_tick` calls for one sid, both
      below `roll_trigger_prem` → exactly one roll, one close, one open
- [x] 1.5 `::test_close_and_open_do_not_interleave` — gather a close and an open on one sid; assert
      `get_net_qty` is not read by one between the other's read and place (instrument the fake broker)
- [x] 1.6 `::test_close_reduces_only_this_legs_lots` — broker `net_qty` = 8 lots, leg holds 4 →
      closing order is 4 lots, not 8
- [x] 1.7 `::test_duplicate_leg_for_security_is_rejected` — appending a second `OpenLeg` for a sid
      already tracked raises and emits a critical event
- [x] 1.8 **`::test_legs_never_vanish_under_concurrent_roll`** — the untraced live failure. Drive two
      concurrent rolls on one sid through the real `_rolling` / `_lock_for` machinery; after each
      step assert `sum(lots across _short_legs + _hedge_legs + _momentum_legs) == broker net_qty`.
      **Do not write any fix for the vanishing-leg bug until this test fails.** If it passes, the
      mechanism is elsewhere — investigate and record the finding before proceeding.
- [x] 1.9 `::test_close_all_closes_orphan_position` — broker holds a position no leg list references →
      square-off closes it and emits a critical event
- [x] 1.10 `::test_stop_half_uses_the_close_path` — `stop_half` (`on_tick:531-546`) calls
      `self._place(sid, seg, "BUY", close_lots)` **directly** at `:536`: it hardcodes `BUY` with no
      `net_qty` sign check, takes no `_lock_for(sid)`, and mutates `leg.lots` at `:537` *after* the
      order is placed. On a misclassified (long) leg this grows the position exactly as the roll path
      did. Assert a partial close on a positive-`net_qty` leg places `SELL`, holds the lock, and
      leaves `leg.lots` consistent with the broker.
- [x] 1.11 Record which of 1.1–1.10 fail on `HEAD`. Any that pass mean the hypothesis is wrong for
      that item — write down what actually happens before changing code.

## 2. Roll becomes all-or-nothing
- [x] 2.1 `_roll_leg` (`directional_strangle.py:1369`) resolves spot/instrument/premium before any close
- [x] 2.2 Close-then-reopen ordering moved to after the last precondition check
- [x] 2.3 The `skipped_*` branches return having placed no order
- [x] 2.4 Verified with 1.1–1.3 (`test_roll_atomicity.py`, all green)

## 3. Atomic roll guard
- [x] 3.1 The rolling-claim check + `self._rolling.add(sid)` happen as one step under `_lock_for(sid)`
      in `on_tick`
- [x] 3.2 `_roll_leg` no longer claims `_rolling` itself; `finally: discard` still releases it
- [x] 3.3 Lock is not held across the full roll (claim is released before `_roll_leg` runs) —
      non-reentrant-lock deadlock avoided; p99 not measured under load in this environment (no
      live paper session run — see section 8)
- [x] 3.4 Verified with 1.4 (`test_concurrent_roll_runs_once`)

## 4. Lock the close path
- [x] 4.1 `_close_leg` (shared by short/hedge/momentum) acquires `_lock_for(sid)` around
      `get_net_qty` → `_place`
- [x] 4.2 Lock acquired exactly once per sid per operation; `_roll_leg` releases `_rolling` before
      calling `_close_leg`/`_open_short`, avoiding re-entrancy on `asyncio.Lock`
- [x] 4.3 `_close_matching_hedge` operates on the hedge's own sid — no lock-ordering cycle with the
      short leg's lock
- [x] 4.4 `stop_half` (`on_tick`) routes through shared `_partial_close`, which holds the lock and
      derives side from `net_qty`
- [x] 4.5 Verified with 1.5, 1.10

## 5. One leg per security
- [x] 5.1 Replaced the three lists with `self._legs: dict[security_id, OpenLeg]` (`kind` field on
      `OpenLeg`); `_add_leg` raises on a duplicate sid. `_short_legs`/`_hedge_legs`/`_momentum_legs`
      kept as read-only properties for existing call sites.
- [x] 5.2 `close_lots` derives from `min(leg.lots, broker_lots)`, not a bare `net_qty // lot_size`
- [x] 5.3 `leg.lots`/`net_qty` disagreement emits `LEG_STATE_DIVERGED`; closes the smaller of the two
      (added a `close_lots == 0` guard during Phase F review so a sub-lot residual doesn't get
      falsely marked fully closed)
- [x] 5.4 Removal is by `security_id` via `_remove_leg`, not list-identity filtering
- [x] 5.5 All read sites (`on_tick`, `_close_all`, `state`, `_rehydrate_legs`) updated for the dict
- [x] 5.6 Verified with 1.6, 1.7 (1.7's test rewritten in Phase F review — see
      `test_duplicate_leg_for_security_is_rejected`)

## 6. Divergence detection
- [x] 6.1 `LEG_STATE_DIVERGED` added to `pdp/events/models.py`
- [x] 6.2 `state()` compares per-sid in-memory lots against broker net-qty; emits on mismatch
- [x] 6.3 Emission is per-detection (not polled/looped), so it does not alert-storm the way
      `POSITION_RECONCILE_MISMATCH` did — no separate rate-limit mechanism was needed
- [x] 6.4 Verified with 1.8 (`test_legs_never_vanish_under_concurrent_roll`)

## 7. Square-off stops trusting memory
- [x] 7.1 `_close_all` enumerates broker open positions via `_broker_positions()`
- [x] 7.2 Closes every leg in `self._legs`, then closes any broker position absent from it (orphan),
      emitting `LEG_STATE_DIVERGED` per orphan
- [x] 7.3 Orphan close re-checks `get_net_qty` under the lock before placing (handles a leg that
      cleared between the enumeration and the close)
- [x] 7.4 Verified with 1.9 (`test_close_all_closes_orphan_position`)

## 8. Paper-session validation (the real acceptance gate)
- [ ] 8.1 One full paper session, `dev:trade` only, no reload — **not run in this environment**
- [ ] 8.2 Zero `LEG_STATE_DIVERGED` events — blocked on 8.1
- [ ] 8.3 Every `ROLLED` event has `result=ok` or a `skipped_*` with no accompanying close — blocked on 8.1
- [ ] 8.4 No security's lot count ever exceeds `_max_leg_lots()` — blocked on 8.1
- [ ] 8.5 At square-off, broker open positions = 0 and the leg structure is empty — blocked on 8.1
- [ ] 8.6 Day P&L reconciles against `paper_journal` within ±5% — blocked on 8.1

## 9. Docs + validation
- [x] 9.1 `backend/pdp/strategies/CLAUDE.md`: documented the one-leg-per-security invariant and the
      lock discipline
- [x] 9.2 `task test` green (1131 passed, 0 failed, 2026-07-13)
- [x] 9.3 `openspec validate --strict strangle-close-path-atomicity` passes

## Status (2026-07-13)

Sections 1–7 and 9 verified against code (not just checkboxes) during `papergapfix` Phase F: the
`_legs` dict, `_add_leg`/`_remove_leg`, `_lock_for`-guarded `_close_leg`/`_roll_leg`/`_partial_close`,
`LEG_STATE_DIVERGED` emission, and orphan reconciliation in `_close_all` all exist and are exercised
by `test_roll_atomicity.py` (10/10 passing). Section 8 (live paper-session acceptance gate) requires
a real `dev:trade` session during market hours and was not run in this environment — remains open for
a deploy-day check, same category as the blocked items in `dhan-same-day-data` and
`indicator-history-depth`.
