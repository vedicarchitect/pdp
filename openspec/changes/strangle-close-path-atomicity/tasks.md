# Tasks — strangle-close-path-atomicity

> **Prerequisite:** `dev-reload-scoping`. Editing strategy code during a session currently restarts
> the backend and re-triggers the rehydration bug, corrupting every observation you make here.
>
> **All work is paper-only.** Do not set `LIVE=1` at any point in this change.

## 1. Reproduce before fixing — these tests must FAIL on today's code
- [ ] 1.1 `tests/strategies/test_roll_atomicity.py::test_skipped_no_spot_leaves_position_open`
      — `_last_spot = None`, trigger a roll → assert the short leg is still in `_short_legs`, the
      matching hedge is still open, and **zero** orders were placed
- [ ] 1.2 `::test_no_instrument_leaves_position_open` — `resolve_otm_option` returns `None` → same assertions
- [ ] 1.3 `::test_low_premium_leaves_position_open` — new premium < `roll_target_min_prem` → same assertions
- [ ] 1.4 `::test_concurrent_roll_runs_once` — `asyncio.gather` two `on_tick` calls for one sid, both
      below `roll_trigger_prem` → exactly one roll, one close, one open
- [ ] 1.5 `::test_close_and_open_do_not_interleave` — gather a close and an open on one sid; assert
      `get_net_qty` is not read by one between the other's read and place (instrument the fake broker)
- [ ] 1.6 `::test_close_reduces_only_this_legs_lots` — broker `net_qty` = 8 lots, leg holds 4 →
      closing order is 4 lots, not 8
- [ ] 1.7 `::test_duplicate_leg_for_security_is_rejected` — appending a second `OpenLeg` for a sid
      already tracked raises and emits a critical event
- [ ] 1.8 **`::test_legs_never_vanish_under_concurrent_roll`** — the untraced live failure. Drive two
      concurrent rolls on one sid through the real `_rolling` / `_lock_for` machinery; after each
      step assert `sum(lots across _short_legs + _hedge_legs + _momentum_legs) == broker net_qty`.
      **Do not write any fix for the vanishing-leg bug until this test fails.** If it passes, the
      mechanism is elsewhere — investigate and record the finding before proceeding.
- [ ] 1.9 `::test_close_all_closes_orphan_position` — broker holds a position no leg list references →
      square-off closes it and emits a critical event
- [ ] 1.10 `::test_stop_half_uses_the_close_path` — `stop_half` (`on_tick:531-546`) calls
      `self._place(sid, seg, "BUY", close_lots)` **directly** at `:536`: it hardcodes `BUY` with no
      `net_qty` sign check, takes no `_lock_for(sid)`, and mutates `leg.lots` at `:537` *after* the
      order is placed. On a misclassified (long) leg this grows the position exactly as the roll path
      did. Assert a partial close on a positive-`net_qty` leg places `SELL`, holds the lock, and
      leaves `leg.lots` consistent with the broker.
- [ ] 1.11 Record which of 1.1–1.10 fail on `HEAD`. Any that pass mean the hypothesis is wrong for
      that item — write down what actually happens before changing code.

## 2. Roll becomes all-or-nothing
- [ ] 2.1 `directional_strangle.py:1181` — restructure `_roll_leg`: resolve `spot`, `session_maker`,
      `resolve_otm_option`, and the new premium **before** any close
- [ ] 2.2 Move `_close_short_leg(leg, "roll")` (`:1189`) and `_close_matching_hedge(leg)` (`:1190`)
      to after the last precondition check
- [ ] 2.3 The three `skipped_*` branches (`:1200`, `:1221`, `:1240`) return having placed no order
- [ ] 2.4 Verify with 1.1–1.3

## 3. Atomic roll guard
- [ ] 3.1 `on_tick:519` — move the `sid not in self._rolling` check and `self._rolling.add(sid)` into
      one step under `_lock_for(sid)`
- [ ] 3.2 Remove `self._rolling.add(sid)` from `_roll_leg:1184`; keep the `finally: discard` at `:1257`
- [ ] 3.3 Confirm the lock is not held across the `await`s that place orders if that would serialise
      unrelated ticks — measure; the roll path is not the hot path, so holding it is acceptable if
      tick→WS p99 stays ≤ 50ms (non-negotiable #5)
- [ ] 3.4 Verify with 1.4

## 4. Lock the close path
- [ ] 4.1 `_close_short_leg:1326`, `_close_hedge_leg:1386`, `_close_momentum_leg:1129` acquire
      `_lock_for(leg.security_id)` around the `get_net_qty` (`:1353`) → `_place` (`:1378`) sequence
- [ ] 4.2 Audit for lock re-entrancy: `_roll_leg` → `_close_short_leg` → `_open_short` must not
      deadlock on the same sid. `asyncio.Lock` is **not** re-entrant — restructure so the lock is
      acquired exactly once per sid per operation, or use an explicit non-reentrant call chain
- [ ] 4.3 `_close_matching_hedge:1438` closes a *different* sid — confirm no lock-ordering cycle
- [ ] 4.4 `on_tick:531-546` (`stop_half`) must route its partial close through a shared helper that
      holds the lock and derives the side from `net_qty`, instead of calling `_place(..., "BUY", ...)`
      raw at `:536`. Capture exit fields before mutating `leg.lots` (that part is already correct).
- [ ] 4.5 Verify with 1.5, 1.10

## 5. One leg per security
- [ ] 5.1 Replace the three lists with a single `dict[security_id, OpenLeg]` plus a `kind` field on
      `OpenLeg`, or keep the lists and add a `_leg_by_sid` index — either way, appending a duplicate
      sid raises. Prefer the dict: it makes the invariant unrepresentable.
- [ ] 5.2 `close_lots` derives from `leg.lots`, not `abs(net_qty) // lot_size` (`:1357`)
- [ ] 5.3 When `leg.lots` and `net_qty` disagree, emit `LEG_STATE_DIVERGED` and close the smaller of
      the two — never more than the broker holds
- [ ] 5.4 Replace identity removal `[l for l in self._short_legs if l is not leg]` (`:1355`, `:1384`)
      with removal by `security_id`
- [ ] 5.5 Update `on_tick:505`, `:512`, `_close_all:1299`, `state:1447`, `_rehydrate_legs:1772`,
      `:879`, `:1898` for the new structure
- [ ] 5.6 Verify with 1.6, 1.7

## 6. Divergence detection
- [ ] 6.1 Add `LEG_STATE_DIVERGED` to `pdp/events/models.py`
- [ ] 6.2 `state():1447` compares per-sid in-memory lots against broker net-qty; emits on mismatch
- [ ] 6.3 Rate-limit the event to once per `(sid, divergence-shape)` per session — this must not
      alert-storm the way `POSITION_RECONCILE_MISMATCH` did in paper mode
- [ ] 6.4 Verify with 1.8

## 7. Square-off stops trusting memory
- [ ] 7.1 `_close_all:1299` enumerates broker open positions for the strategy's securities
- [ ] 7.2 Closes every one, including those absent from the leg structure; critical event per orphan
- [ ] 7.3 Post-condition assertion: broker reports zero open positions for the day's securities
- [ ] 7.4 Verify with 1.9

## 8. Paper-session validation (the real acceptance gate)
- [ ] 8.1 One full paper session, `dev:trade` only, no reload
- [ ] 8.2 Zero `LEG_STATE_DIVERGED` events
- [ ] 8.3 Every `ROLLED` event has `result=ok` or a `skipped_*` with **no** accompanying `LEG_CLOSE`
      for that sid in the same second
- [ ] 8.4 No security's lot count ever exceeds `_max_leg_lots()`
- [ ] 8.5 At square-off, broker open positions = 0 and the leg structure is empty
- [ ] 8.6 Day P&L reconciles against `paper_journal` within ±5% (non-negotiable: backtest-vs-paper)

## 9. Docs + validation
- [ ] 9.1 `backend/pdp/strategies/CLAUDE.md`: document the one-leg-per-security invariant and the
      lock discipline (open **and** close hold `_lock_for(sid)`)
- [ ] 9.2 `task test` green against the recorded baseline
- [ ] 9.3 `openspec validate --strict strangle-close-path-atomicity` passes
