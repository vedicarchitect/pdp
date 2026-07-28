# Tasks — strangle-parity-and-ops-hardening

## 1. Squareoff price source (`eod-walkthrough-report` §6.3)
- [ ] 1.1 `strangle_sim.py:780`: change `close_all(ist_dt, db.open, "squareoff")` to read the same
      `price_at(..., prefer="close")` every other exit path uses.
- [ ] 1.2 Check `close_all(sqoff_dt, nifty_close, "squareoff_end")` (`:868`, the day-loss-cap
      squareoff) already uses close — confirm and leave as-is, or align if it doesn't.
- [ ] 1.3 Regression test: a synthetic day where a leg's 15:10 open and close bars differ; assert
      the squareoff fill price equals the close, not the open.
- [ ] 1.4 Re-run `walkthrough_checks.py`'s `F-PRICE-SRC` detector against 2026-07-27 and confirm it
      clears.

## 2. Restore `leg_buckets` after a roll (`eod-walkthrough-report` §6.1)
- [ ] 2.1 `_roll_leg` (`strangle_sim.py:685-717`): after `legs[opt_type] = nl`, re-insert the
      pre-roll bucket into `leg_buckets[opt_type]` (capture it before `close_leg` pops it at `:572`).
- [ ] 2.2 Regression test: with `take_profit_extreme_only: true`, roll a `complete_bull`-bucket leg,
      then drive its replacement to the TP threshold; assert TP still fires (currently does not).
- [ ] 2.3 Confirm no other reader of `leg_buckets` (the `emit()` trace snapshot at `:767`, the
      warehouse `build_decision_docs` path) assumed the old missing-after-roll behavior.

## 3. Backtest/live take-profit formula parity (`eod-walkthrough-report` §6.2)
- [ ] 3.1 Confirm the divergence precisely: backtest fires TP when
      `captured >= take_profit_pct * credit` (`strangle_sim.py:666`, equivalent to
      `ltp <= entry * (1 - take_profit_pct)`); live fires at `ltp <= entry * take_profit_pct`
      (`directional_strangle.py:846`). These agree only at `take_profit_pct = 0.5`.
- [ ] 3.2 Change the backtest condition to match live's actual traded formula
      (`ltp <= entry * take_profit_pct`) rather than the "captured X% of credit" reading.
- [ ] 3.3 Regression test: run the backtest at `take_profit_pct=0.3` and `0.7` (values where the two
      formulas previously disagreed) and assert the TP fire price matches
      `entry * take_profit_pct` exactly.
- [ ] 3.4 Confirm none of the three promoted live configs use a `take_profit_pct` other than 0.5
      (already true per `directional_strangle_{nifty,banknifty,sensex}.yaml`) — if so, no
      re-baseline is triggered by this fix; record that check's result in this task's own note.

## 4. 2026-07-27 live-vs-backtest divergence (found via `/backtest:vs-paper`)
- [ ] 4.1 Pull the live strangle event log (OpenSearch `pdp-strangle-events-*` /
      `fetch_session_events`) for `directional_strangle_nifty` on 2026-07-27.
- [ ] 4.2 Build the minute-level decision diff (`minute_diff` / `annotate_minute_divergence` from
      `pdp/backtest/paper_compare.py`) between that live event log and a fresh
      `simulate_strangle_day` replay's `backtest_decisions`-shaped trace for the same date.
- [ ] 4.3 Identify the first divergent minute and its cause: bias-vote mismatch, entry timing
      (live's first fill is 10 minutes later — 10:25 IST vs backtest's 10:15 IST), or an exit-path
      difference already covered by tasks 1–3.
- [ ] 4.4 Apply whatever fix the root cause requires. If it's already covered by tasks 1–3, cross
      reference here rather than duplicating; if it's new, add the fix + its own spec delta before
      archiving this change.
- [ ] 4.5 Re-run `/eod:walkthrough 2026-07-27` and re-fetch paper's 2026-07-27 realized P&L; confirm
      the net/fill-count/round-trip gap has closed or is now attributable to a named, documented
      cause.

## 5. OpenSearch-down startup resilience
- [ ] 5.1 `InfraGroup.start()` (`pdp/runtime/groups.py:32-68`): wrap
      `await ensure_templates(os_client, ...)` in a short overall `asyncio.wait_for` timeout (a few
      seconds) instead of letting it retry against a refused connection for the ~100s observed with
      OpenSearch down.
- [ ] 5.2 On timeout, log a warning (matching `ensure_templates`'s own per-family
      `ensure_template_failed` pattern) and continue starting the rest of the infra group — do not
      raise, since `InfraGroup.required = True` would otherwise refuse the whole API over a
      non-critical logging dependency.
- [ ] 5.3 Regression test: boot the app (or a narrow harness around `InfraGroup.start()`) with
      `OPENSEARCH_ENABLED=1` and no reachable OpenSearch; assert startup completes within a few
      seconds, not ~100s.
- [ ] 5.4 Update `pdp/observability/CLAUDE.md`'s "OS down = no-op" line to explicitly cover the
      one-time boot-path template registration, not just the steady-state bulk-flush loop, so the
      documented contract matches reality.

## 6. Verification
- [ ] 6.1 `task test`: no regressions against the pre-change baseline.
- [ ] 6.2 `ruff check` clean on every modified file.
- [ ] 6.3 `openspec validate --strict strangle-parity-and-ops-hardening`.
- [ ] 6.4 Re-run `/eod:walkthrough 2026-07-27` one more time after all fixes land; confirm the
      FINDINGS section is empty (or lists only newly-discovered, separately-tracked items).
