# Tasks — strangle-entry-fill-race-and-latch

## 0. Diagnostics (read-only, done)
- [x] 0.1 Confirm strategies are running + evaluating bias but opening no legs (NIFTY/BANKNIFTY
      `legs:[]` all day; SENSEX 1 leg). **Done 2026-07-17** from `logs/directional_strangle_*/2026-07-17.log`.
- [x] 0.2 Confirm the abort mechanism: `fill_avg_px_zero` count today (=6) and that instruments /
      option feed / VIX / snapshots are all healthy (ruled out). **Done** via Redis `ltp:*`,
      Postgres `instruments`, OpenSearch `pdp-logs-2026.07`.
- [x] 0.3 Confirm the latch: `_current_bucket` set at `directional_strangle.py:651` before
      `_open_bucket` at `:654-655`. **Done.**

## 1. Return-contract: opens report how many legs opened
- [x] 1.1 `_open_short` returns `bool` — True iff the short leg **remains** open afterwards
      (`leg.security_id in self._legs`, which also catches the `naked_hedge_averted` square-off);
      every early-return path returns False.
- [x] 1.2 `_open_hedge` return left unconsumed — `_open_short`'s `self._legs` check already derives
      correctness including the hedge-averted square, so no signature change was needed (minimal edit).
- [x] 1.3 `_open_bucket` returns `int` = number of short legs opened (sum of `_open_short` PE+CE).
- [x] 1.4 `_open_momentum` unchanged (momentum disabled by config); return not consumed.

## 2. Commit bucket only on a filled open (the latch fix)
- [x] 2.1 In `on_bar`, when confirmation is met: close old legs on bucket_change as today, then call
      `_open_bucket`; advance `_current_bucket` + clear pending **only if it returned > 0**.
- [x] 2.2 On a zero-leg open, retain `_pending_bucket`/count so the next bar retries; do not advance
      `_current_bucket`. DTE-gated bars do not advance `_current_bucket`.
- [x] 2.3 Churn is bounded to the 5m bar cadence; a partial open (`opened < expected`) commits and
      emits `entry_aborted reason=partial_open` rather than looping.

## 3. Close the subscribe→fill race
- [x] 3.1 Added `entry_ltp_wait_s` param (default 4.0).
- [x] 3.2 `_await_option_ltp` polls `ctx.market.ltp_with_age` (and the in-process cache) up to
      `entry_ltp_wait_s`; called in `_open_short` right after `_subscribe_option`. (Hedge already has
      its own `_hedge_price_wait_s` scan-retry.)
- [x] 3.3 Existing `cancel_open_entry_orders` on abort retained.

## 4. Surface aborts
- [x] 4.1 Added `StrangleEventType.ENTRY_ABORTED = "entry_aborted"`.
- [x] 4.2 `on_bar` emits `ENTRY_ABORTED` on zero-open (`fill_unresolved`) and partial open
      (`partial_open`) with `bucket`, `pe_lots`, `ce_lots`, `opened`, `reason`.

## 5. Tests
- [x] 5.1 `test_failed_open_does_not_latch_bucket_and_retries_next_bar`: cold open → no leg,
      `_current_bucket` unchanged, `entry_aborted` emitted; warm retry → legs open, bucket advances.
- [x] 5.2 `test_await_option_ltp_true_when_tick_arrives_within_wait` +
      `test_await_option_ltp_false_when_no_tick_within_wait`.
- [x] 5.3 Existing `test_single_bar_bucket_flip_does_not_churn` / `test_sustained_bucket_change...`
      still pass (37 in-file + 28 cross-cutting green).
- [x] 5.4 `task test` full green (baseline 1131) — run before archive. **Done (2026-07-17): 1187
      passed, 0 failed.** Ruff on `directional_strangle.py`/`strategy/log.py` confirmed net-zero
      new errors vs. HEAD (22 vs. base 23 pre-existing findings, same codes/lines shifted; new
      test-file findings are identical pre-existing style nits already present in those files).

## 6. Verify + archive
- [x] 6.1 `openspec validate --strict strangle-entry-fill-race-and-latch` → valid.
- [ ] 6.2 Live-paper smoke on the next market day: NIFTY/BANKNIFTY open legs; any abort visible in
      the activity log + Execution Console. **(Blocked: after today's close; next live day.)**
- [ ] 6.3 `openspec archive strangle-entry-fill-race-and-latch`.
