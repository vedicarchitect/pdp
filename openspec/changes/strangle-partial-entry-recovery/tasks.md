# Tasks — strangle-partial-entry-recovery

> **All work is paper-only.** Do not set `LIVE=1` at any point in this change.
> **Prerequisite (tooling):** `dev-reload-scoping` is archived — edit strategy code freely; `task dev`
> is scoped to `backend/pdp` and refuses to kill a live `dev:trade` / during market hours.

## 1. Reproduce before fixing — these tests must FAIL on today's code
- [x] 1.1 `tests/strategies/test_entry_recovery.py::test_aborted_side_reopens_next_bar` — neutral
      bucket wanting PE+CE; fake fill-price returns 0 for PE on the first bar (CE resolves) → after the
      open bar the book is CE-only; on the next bar (bucket unchanged, PE price now resolves) assert the
      PE short opens and the book holds both sides + hedges
- [x] 1.2 `::test_both_sides_aborted_then_recover` — both sides' fills return 0 on the open bar (book
      flat); on later bars prices resolve → assert both sides open
- [x] 1.3 `::test_take_profit_side_not_resurrected` — PE opens (realized), then take-profit closes it →
      assert PE is NOT re-opened on subsequent unchanged-bucket bars
- [x] 1.4 `::test_stop_gated_side_not_recovered` — CE opens then stops (enters `_stop_gate`) → assert
      recovery skips CE while gated
- [x] 1.5 `::test_recovery_is_bounded_and_emits_unfilled` — a side whose price never resolves →
      exactly `entry_recovery_max_attempts` attempts, then one `ENTRY_SIDE_UNFILLED`, then no further
      attempts until a bucket change
- [x] 1.6 `::test_bucket_change_resets_recovery` — after a side is marked unfilled, a confirmed bucket
      change resets attempt counters/realized-set and opens the new bucket's legs afresh
- [x] 1.7 `::test_recovery_respects_entry_allowed_and_neutral_no_trade` — no recovery before the
      entry-after time, when gated, when `neutral_no_trade` in neutral, or when lot size is degraded

## 2. Implement — episode intent state
- [x] 2.1 Add `entry_recovery_enabled: bool = True` and `entry_recovery_max_attempts: int = 3` to
      `StrategyConfig` (`from_dict`/`to_dict`/YAML round-trip); read into the strategy in `__init__`
- [x] 2.2 Add per-episode state: `_bucket_target: dict[str,int]`, `_bucket_realized: set[str]`,
      `_recovery_attempts: dict[str,int]`; reset them wherever `_current_bucket` is set on a confirmed
      change (`directional_strangle.py:651`)
- [x] 2.3 Set `_bucket_target = {"PE": pe_lots, "CE": ce_lots}` when a bucket is acted on
- [x] 2.4 Mark a side realized in `_open_short` on successful `_add_leg` (add the leg's `opt_type` to
      `_bucket_realized`); add `_open_short_lots(side)` helper summing open short legs of that type

## 3. Implement — recovery/reconcile pass
- [x] 3.1 Extract a `_reconcile_bucket_composition(spot)` coroutine implementing the per-side loop from
      `design.md` (skip when have-side / realized / stop-gated / target 0; bound by
      `entry_recovery_max_attempts`; emit `ENTRY_RECOVERY_ATTEMPT`, and terminal `ENTRY_SIDE_UNFILLED`)
- [x] 3.2 Call it on the bucket-unchanged path (replace the no-op `else` at `:656`) and once more right
      after the initial `_open_bucket` on a confirmed change, both under the existing `entry_allowed` /
      `done_for_day` / `neutral_no_trade` / `lot_size_degraded` / `entry_recovery_enabled` guards
- [x] 3.3 Add `ENTRY_RECOVERY_ATTEMPT` + `ENTRY_SIDE_UNFILLED` to `StrangleEventType` and the event
      taxonomy test/enum

## 4. Verify
- [x] 4.1 Section-1 tests now PASS; full `tests/strategies/` green
- [x] 4.2 `task test` (backend suite): **1201 passed** (up from 1194; +7 new tests). `ruff check` on
      touched files diffed against HEAD: identical 23 pre-existing findings, zero new. `pyright` on
      touched files diffed against HEAD: 60 vs 59 findings — the +1 is one more instance of the
      file's existing untyped-`_stop_gate`-dict pattern (8 other call sites already carry the same
      `reportUnknownMemberType`, since `_stop_gate: dict[str, dict]` has no generic type args
      project-wide); not a new category of error, and out of this change's scope to fix (see
      design.md's "Out of scope").
- [x] 4.3 Confirm no behavior change for a fully-successful entry (a bar where both sides open first
      try makes zero recovery attempts — `_bucket_realized == {"PE","CE"}`) — verified directly:
      `_recovery_attempts == {}` and zero `ENTRY_RECOVERY_ATTEMPT` events.
- [x] 4.4 Backtest parity spot-check: `grep` confirms `pdp/backtest/` and `backtest/` have zero
      references to `directional_strangle`/`entry_recovery`/`_reconcile_bucket_composition` — the
      simulator path is provably disjoint, not just untouched by coincidence. Full `tests/backtest/`
      suite passed unchanged in the same `task test` run, proving no regression.

## 5. OpenSpec bookkeeping
- [x] 5.1 `openspec validate --strict strangle-partial-entry-recovery` → valid
- [x] 5.2 Update memory: new note `strangle_partial_entry_recovery.md` (linked from
      `leg_rehydration_misclassification_bug.md`) with the 2026-07-15 feed-reconnect one-sided-entry
      finding and this fix; indexed in `MEMORY.md`
- [ ] 5.3 `openspec archive strangle-partial-entry-recovery` after live/boot smoke on the next market
      day — same gate as the other 3 in-flight changes; also blocked on the user's explicit
      "review finally once all done before commit and submit" instruction (no commit until reviewed)

> **2026-07-17 `/opsx:verify` + `/code-review` (high effort) found and FIXED 2 correctness gaps**
> before archive: (1) `naked_hedge_averted` used to leave `_bucket_realized` permanently set,
> defeating recovery for that side for the rest of the episode — fixed in `_open_short`
> (`directional_strangle.py:1256-1263`): a short is only marked realized once it survives the hedge
> step (`opened = leg.security_id in self._legs`), so a hedge-averted square-off is reported as "not
> opened" and retried on the next bar. (2) `_recovery_attempts`/`_bucket_realized`/`_bucket_target`
> used to never reset on day rollover while `_current_bucket` intentionally persists across days, so
> an exhausted counter from day N stayed pinned into day N+1 — fixed in `_maybe_reset_day`
> (`directional_strangle.py:2086`): `_recovery_attempts` resets daily; `_bucket_realized` is
> deliberately NOT reset (a side closed this episode must never resurrect across a day boundary).
> Regression coverage added: `test_naked_hedge_averted_side_is_recovered` +
> `test_recovery_attempts_reset_on_day_rollover` in `test_entry_recovery.py`. Full backend suite
> green after the fix. Both gaps closed; only the live/boot smoke gate (5.3) remains before archive.
