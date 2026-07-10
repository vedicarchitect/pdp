# Tasks — dhan-same-day-data

> **Investigation first.** Tasks 2–5 branch on what task 1 finds. Do not estimate this change or
> write a fix for the restart hole before task 1 is complete and its answer is written down.

## 1. Establish ground truth (blocking — nothing else starts until this is answered)
- [ ] 1.1 `backend/scripts/oneoff/probe_dhan_same_day.py`: call `intraday_minute_data` for NIFTY
      (sid `13`, `IDX_I`) with `to_date = today`, **during market hours** (~11:00 IST). Record every
      returned candle timestamp.
- [ ] 1.2 Repeat after the close (~16:00 IST). Diff the two responses.
- [ ] 1.3 Determine which holds:
      **(a)** today's completed candles are returned;
      **(b)** nothing for today is returned;
      **(c)** today's candles are returned *including a still-forming final candle*.
- [ ] 1.4 Repeat for `historical_daily_data` (the `1D` / `1w` path at `warmup.py:370`)
- [ ] 1.5 Write the answer into this change's README. Everything below depends on it.
- [ ] 1.6 **Resolve the `live-supertrend-session-warmup` contradiction.** That change is archived
      (`openspec/changes/archive/2026-06-16-live-supertrend-session-warmup`) with 10/10 tasks checked,
      but memory `live_supertrend_warmup_gap` records it as "spec+design done, NOT implemented,
      deferred indefinitely". Read its `tasks.md` against the current source and establish which is
      true. Correct whichever artefact is wrong.

## 2. Guard against incomplete candles (safe under all three answers — do this regardless)
- [ ] 2.1 `tests/indicators/test_warmup.py`: a fetch at 11:07 IST returning a 5m candle stamped 11:05
      → discarded, not persisted, not seeded
- [ ] 2.2 A fetch at 16:00 IST → the 15:25 candle is retained
- [ ] 2.3 `warmup.py`: reject any bar where `bar_time + timeframe > now` before `_persist_bars` and
      before seeding
- [ ] 2.4 Apply the same guard to any other path that writes `market_bars` from a broker fetch
      (`grep -rn "_persist_bars\|market_bars" backend/pdp backend/scripts`)

## 3. Timezone correctness (safe under all three answers)
- [ ] 3.1 `warmup.py:359` — replace `datetime.now(UTC) + timedelta(hours=5, minutes=30)` with
      `datetime.now(ZoneInfo("Asia/Kolkata"))`
- [ ] 3.2 Test the boundary: 18:29 UTC → 2026-07-09; 18:31 UTC → 2026-07-10
- [ ] 3.3 `grep -rn "hours=5, minutes=30" backend/pdp` — fix every other fixed-offset IST derivation
      or record why it is safe. This is the pattern that caused the `broker-sync-visibility`
      snapshot-date bug.

## 4. If answer is (c) — audit and clean existing corruption
- [ ] 4.1 Query `market_bars` for suspected partial candles: `high == low == open == close`, or volume
      anomalously low for the timeframe, or `ts` equal to a session-boundary bucket with a truncated period
- [ ] 4.2 Quantify: how many documents, which `(sid, tf)`, which dates
- [ ] 4.3 Fold the cleanup into `bar-session-anchoring`'s rebuild (it already rewrites 15m/30m/1H
      from the 1m series). Clean the 1m series separately — the rebuild trusts it.

## 5. If answer is (b) — close the restart hole
- [ ] 5.1 Warmup reconstructs today's bars from the 1m `market_bars` written by `BarWriter` before the crash
- [ ] 5.2 Detect the residual gap between the last persisted 1m bar and the restart instant
- [ ] 5.3 Report an irreparable gap as a `blocked` readiness component
      (see `strangle-observability-gaps` task 4) — do not start the strategy on a holed series
- [ ] 5.4 Never advance a tracker across a detected discontinuity
- [ ] 5.5 Tests: reconstructable restart → contiguous series, ready; irreparable → blocked, named interval

## 6. If answer is (a) — verify and document
- [ ] 6.1 Add a regression test asserting today's completed candles are returned and seeded
- [ ] 6.2 Document in `backend/pdp/indicators/CLAUDE.md` that intraday restart warmup is
      self-healing, and why
- [ ] 6.3 Close this change with tasks 2 and 3 only

## 7. Docs + validation
- [ ] 7.1 `backend/pdp/indicators/CLAUDE.md`: the same-day fetch contract, whichever it turns out to be
- [ ] 7.2 `task test` green against the recorded baseline
- [ ] 7.3 `openspec validate --strict dhan-same-day-data` passes
