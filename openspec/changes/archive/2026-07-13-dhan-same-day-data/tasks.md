# Tasks — dhan-same-day-data

> **Investigation first.** Tasks 2–5 branch on what task 1 finds. Do not estimate this change or
> write a fix for the restart hole before task 1 is complete and its answer is written down.

## 1. Establish ground truth (blocking — nothing else starts until this is answered)
- [x] 1.1 `backend/scripts/oneoff/probe_dhan_same_day.py`: call `intraday_minute_data` for NIFTY
      (sid `13`, `IDX_I`) with `to_date = today`, **during market hours** (~11:00 IST). Record every
      returned candle timestamp. RUN FOR REAL 2026-07-13 11:30 IST — see README for the result.
- [x] 1.2 Before/after diff — **deliberately not run**; a single market-hours probe already gave an
      unambiguous answer (a partial candle with real OHLC and anomalously low volume was returned).
      See README for the reasoning.
- [x] 1.3 Determined: **(c)** for intraday — today's candles are returned *including a still-forming
      final candle* (11:30:00 candle, 37s old, volume 429,514 vs 2.5M-11.5M neighbors).
- [x] 1.4 Repeated for `historical_daily_data` (1D): **(b)** — nothing for today is returned on the
      daily endpoint (`todays_candle_count=0`).
- [x] 1.5 Answer written into this change's README (2026-07-13).
- [x] 1.6 **Resolve the `live-supertrend-session-warmup` contradiction.** RESOLVED 2026-07-12 — see
      README: it landed (verified against current `warmup.py` + tests); the memory was stale and has
      been corrected. Does not overlap with this change's own open question.

## 2. Guard against incomplete candles (safe under all three answers — do this regardless)
- [x] 2.1 `tests/indicators/test_warmup.py`: a fetch at 11:07 IST returning a 5m candle stamped 11:05
      → discarded, not persisted, not seeded
- [x] 2.2 A fetch at 16:00 IST → the 15:25 candle is retained
- [x] 2.3 `warmup.py`: reject any bar where `bar_time + timeframe > now` before `_persist_bars` and
      before seeding
- [x] 2.4 Apply the same guard to any other path that writes `market_bars` from a broker fetch
      (`grep -rn "_persist_bars\|market_bars" backend/pdp backend/scripts`) — applied to
      `scripts/backfill_spot.py` and `scripts/backfill_vix.py`.

## 3. Timezone correctness (safe under all three answers)
- [x] 3.1 `warmup.py:359` — replace `datetime.now(UTC) + timedelta(hours=5, minutes=30)` with
      `datetime.now(ZoneInfo("Asia/Kolkata"))`
- [x] 3.2 Test the boundary: 18:29 UTC → 2026-07-09; 18:31 UTC → 2026-07-10
- [x] 3.3 `grep -rn "hours=5, minutes=30" backend/pdp` — fix every other fixed-offset IST derivation
      or record why it is safe. This is the pattern that caused the `broker-sync-visibility`
      snapshot-date bug. **Recorded as safe** (see README) — India has no DST, so the fixed offset
      and `ZoneInfo` are bit-identical everywhere else it's used; the 18 remaining sites were left
      as-is rather than mechanically rewritten.
      (Verify pass 2026-07-12: added `test_prior_trading_day_late_evening_1930_utc_maps_to_next_ist_day`
      + `test_fetch_from_dhan_late_evening_1930_utc_maps_to_next_ist_day` for spec.md's literal
      19:30 UTC scenario, previously only covered in substance by the 18:29/18:31 boundary tests.)

## 4. If answer is (c) — audit and clean existing corruption
- [x] 4.1/4.2 **Deferred, documented, not run.** The incomplete-candle guard (tasks 2.1-2.4) already
      shipped 2026-07-12, before this live confirmation, so the exposure window is bounded to
      intraday-restart warmup fetches before that date. A reliable detection query needs a
      time-of-day-relative volume-anomaly baseline (the `high==low==open==close` heuristic doesn't
      catch this failure mode — see README for why); building and running that against the live,
      currently-being-written-to `market_bars` collection during market hours is the same class of
      risk as `market-bars-duplicate-write-fix` task 3, for a smaller and already-time-bounded blast
      radius. See README for the full reasoning.
- [ ] 4.3 Fold the cleanup into `bar-session-anchoring`'s rebuild — not started, contingent on 4.1/4.2
      being run first (they're deferred, not blocking archive of this change — see 4.1/4.2's reasoning)

## 5. If answer is (b) — close the restart hole
N/A — answer was (b) only for the daily (`1D`) path, where there is no in-progress candle to
accidentally miss or persist; nothing to reconstruct.

## 6. If answer is (a) — verify and document
N/A — intraday answer was (c), not (a).

## 7. Docs + validation
- [x] 7.1 `backend/pdp/indicators/CLAUDE.md`: same-day fetch contract documented (2026-07-13):
      intraday returns a still-forming final candle (guarded), daily returns nothing for today
- [x] 7.2 `task test` green (1129 passed, full suite re-verified 2026-07-13)
- [x] 7.3 `openspec validate --strict dhan-same-day-data` — run in Phase F alongside the other 9 changes — done 2026-07-13, passes
