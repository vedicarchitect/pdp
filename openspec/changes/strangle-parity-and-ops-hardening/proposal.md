# strangle-parity-and-ops-hardening

## Why

Three real gaps surfaced in one session while running `/eod:walkthrough` and `/backtest:vs-paper`
for 2026-07-27 — none of them data-completeness issues, all of them either a live bug or a genuine
unexplained divergence:

1. **Backtest/live exit-path parity gaps, deliberately deferred out of `eod-walkthrough-report`**
   (its `tasks.md` §6.1–6.3) are still open and are no longer purely theoretical — this session's
   fresh 2026-07-27 walkthrough tripped the squareoff one (`F-PRICE-SRC`) on the very first re-run
   after the partial-close/VIX fixes landed:
   - `strangle_sim.py:780` closes every leg at `squareoff` using `db.open`, while every other exit
     path (`take_profit`, `pct_stop_half`, `pct_stop_all`, `roll`) reads `price_at(..., prefer=
     "close")`. On 2026-07-27 this alone put the 15:10 fill's recorded spot 9.70 points away from
     the decision bar's own spot.
   - `_roll_leg` (`strangle_sim.py:685-717`) calls `close_leg`, which pops the rolled side out of
     `leg_buckets` (`:572`), then opens the new leg without restoring it. Any leg that rolls while
     `take_profit_extreme_only: true` permanently loses TP eligibility for the rest of the day,
     because `_tp_eligible` (`:664-665`) reads `leg_buckets.get(ot) in _EXTREME` and a missing key
     is never in that set.
   - The backtest's take-profit condition (`strangle_sim.py:666`, `captured >= take_profit_pct *
     credit`, i.e. `ltp <= entry * (1 - take_profit_pct)`) and live's (`directional_strangle.py:
     846`, `ltp <= entry * take_profit_pct`) are **different formulas** that only coincide at
     `take_profit_pct = 0.5` — which is why this has never shown up: all three live YAMLs are
     pinned at 0.5. The moment anyone tunes that knob, backtest and live silently diverge.

2. **A genuine, unexplained live-vs-backtest P&L divergence for 2026-07-27**, found by running
   `/backtest:vs-paper` against the fresh walkthrough replay for that same day (no stored
   `backtest_runs` window currently reaches 2026-07-27, so the comparison was done directly against
   paper's PostgreSQL ledger): paper's `directional_strangle_nifty` closed the day at **net +1,021**
   across **10 round trips / 23 fills**, first fill **10:25 IST**, while the backtest replay of the
   identical day/config closed at **net +5,006** across **7 closed legs / 13 fills**, first fill
   **10:15 IST**. Live traded nearly twice as often, started ten minutes later, and kept a fifth of
   the P&L. Nothing in the gap radar or bias-vote trace explains this — it needs a real
   minute-by-minute decision diff, not a guess.

3. **The API cannot come up promptly when `OPENSEARCH_ENABLED=1` and OpenSearch is not running.**
   Discovered live while starting `task dev` to run the `/backtest:vs-paper` comparison: the
   `required=True` `InfraGroup.start()` (`pdp/runtime/groups.py:32-68`) unconditionally awaits
   `ensure_templates()` (`pdp/observability/mappings.py:198`) before the ASGI lifespan can complete.
   Each template PUT retries against a refused connection for ~2.3s before `ensure_templates`'s own
   try/except catches it and moves to the next family; across all families this held
   `Application startup complete` back by roughly 100 seconds, during which **every** incoming HTTP
   request queued behind the unfinished lifespan and timed out client-side (TCP accept succeeds,
   but Starlette/Uvicorn will not dispatch a request until startup finishes). This contradicts
   `pdp/observability/CLAUDE.md`'s own documented contract — *"OS down = no-op: flush failures log
   one warning and discard; the API + stdout logging are unaffected"* — which is true of the
   steady-state bulk-flush loop but not of this one-time boot-path template registration.

## What Changes

- **Squareoff price source**: `strangle_sim.py`'s `squareoff` exit reads `price_at(..., prefer=
  "close")` like every other exit, instead of `db.open`.
- **Restore `leg_buckets` after a roll**: `_roll_leg` re-inserts the rolled side's original bucket
  into `leg_buckets` after opening the new leg, so `take_profit_extreme_only` continues to apply
  correctly to a rolled leg for the rest of the day.
- **Single-source the take-profit formula**: backtest and live compute the same condition from the
  same `take_profit_pct` semantic. Live's `ltp <= entry * take_profit_pct` is what has actually been
  trading in production; the backtest simulator is corrected to match it (`captured` reframed so the
  fire condition is identical to live's), rather than silently reinterpreting the knob.
- **Root-cause and fix the 2026-07-27 live-vs-backtest divergence**: pull the live strangle event
  log for that date, build the same minute-level decision diff `/backtest:vs-paper --date` produces
  (backtest vs live event sets, normalized onto the shared `bias | entry | scale_in | rollup | exit
  | reentry` vocabulary), and find the first divergent minute. If the cause is one of the three
  parity gaps above, this task confirms it numerically (re-run the walkthrough + re-fetch paper
  after the fix, diff should shrink or clear); if it is something new, it gets its own fix and, if
  warranted, its own follow-up spec delta before this change archives.
- **Bound OpenSearch template registration at boot**: `InfraGroup.start()` no longer lets a down
  OpenSearch hold back `Application startup complete`. `ensure_templates()` gets a short overall
  timeout (a few seconds, not ~100s) and a startup failure there is logged and skipped — consistent
  with the module's own documented "OS down = no-op" contract — rather than silently absorbed one
  slow retry at a time on the boot path.

**Explicitly out of scope** (unchanged from `eod-walkthrough-report`'s own deferral, still a product
decision rather than a bug fix): neutral-bucket straddle / roll-target / opposite-side-cooloff
policy, and re-baselining the promoted NIFTY/BANKNIFTY/SENSEX configs.

## Impact

- **Affected specs**: `directional-strangle` (MODIFIED — squareoff price source, roll bucket
  restoration, TP formula parity all fall under "Leg lifecycle and exits"); `ops-safety` (ADDED —
  bounded startup when OpenSearch is unreachable).
- **Affected code**: `pdp/backtest/strangle_sim.py` (squareoff price, `_roll_leg`, TP condition),
  `pdp/runtime/groups.py` (`InfraGroup.start()`), `pdp/observability/mappings.py`
  (`ensure_templates` timeout).
- **Re-baseline note**: the TP-formula fix only changes backtest behavior for any run using a
  `take_profit_pct` other than 0.5 — none of the three promoted configs do, so no re-baseline is
  triggered by this change. The squareoff price-source fix changes the exact squareoff fill price
  for every run ever produced; whether that's material enough to warrant a re-run is folded into the
  existing, still-open `eod-walkthrough-report` task 6.5 decision, not duplicated here.
