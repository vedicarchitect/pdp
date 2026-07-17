# Tasks — indicator-warmup-derive-from-1m

## 0. Diagnostics (read-only, done)
- [x] 0.1 Confirm DH-905 root cause: `_fetch_from_dhan` single un-chunked window
      (`lookback_days("30m",1000)≈108d`, `1H≈200d`) > Dhan 90-day intraday cap. **Done 2026-07-17.**
- [x] 0.2 Confirm the 1m series is dense enough to derive 15m/30m/1H (5yr backfilled 1m). **Done.**
- [x] 0.3 Confirm the depth gap is cosmetic to trading (893 ≥ 200 `is_warm` floor; EMA9/20/50
      converge so bias is unaffected) — this is a data-completeness/console fix, not the trade fix
      (that is `strangle-entry-fill-race-and-latch`). **Done.**

## 1. Derive derivable timeframes from 1m
- [x] 1.1 `_DERIVABLE_TF_MINUTES = {15m,30m,1H,1h}` (5m intentionally excluded).
- [x] 1.2 `_derive_bars_from_1m(bars_1m, tf_minutes, timeframe)` rolls 1m `BarClosed` into
      session-anchored buckets via `pdp.market.bars._bar_boundary` (canonical import, not `scripts/`).
- [x] 1.3 `_replace_derived_bars` delete-then-insert (TS collection) + `_persist_bars`.
- [x] 1.4 `_warm_one`: for a short derivable TF, read 1m, derive, drop incomplete final bucket
      (`bar_is_complete`), and use+persist only when `len(derived) > len(existing)`; log
      `indicator_warmup_derived_from_1m`. Runs before the Dhan fallback.

## 2. Chunk the Dhan intraday fallback by 90 days
- [x] 2.1 `_ninety_day_chunks(from_d, to_d, max_days=90)` — inclusive ≤90-day windows, contiguous.
- [x] 2.2 `_fetch_from_dhan` loops `intraday_minute_data` per chunk (parse extracted to a local
      `_parse`), concatenates, and logs+skips a failed chunk instead of aborting the whole fetch.
- [x] 2.3 Daily (`historical_daily_data`) left single-call (not intraday-capped).

## 3. Out-of-band depth (ops, no new code needed)
- [x] 3.1 `scripts/backfill_market_bars.py` already derives 15m/30m/1H from 1m (chunked Dhan only
      when 1m absent) — documented as the pre-session job; boot's `indicator_seeding_summary`
      already surfaces residual gaps loudly.
- [ ] 3.2 (Ops) Schedule `task backfill:daily` pre-session on the live host (Windows Task
      Scheduler). Not a code change; recorded for the operator.

## 4. Tests
- [x] 4.1 `test_ninety_day_chunks_splits_over_90_days` + single-window.
- [x] 4.2 `test_derive_bars_from_1m_rolls_up_session_anchored_30m` (bucket count + OHLCV).
- [x] 4.3 `test_fetch_from_dhan_chunks_intraday_over_90_days` (3 calls for 182 days) +
      `test_fetch_from_dhan_daily_is_not_chunked`.
- [x] 4.4 `test_warmup_derives_30m_from_1m_and_skips_dhan` +
      `test_warmup_derive_falls_back_to_dhan_when_1m_absent`.
- [x] 4.5 Existing warmup suite still green (40 passed; the `len(derived) > len(existing)` guard
      preserves `test_warmup_short_emits_exactly_one_warning_with_counts`).
- [x] 4.6 `task test` full green (baseline 1131) — run before archive. **Done (2026-07-17): 1187
      passed, 0 failed.** Ruff on `warmup.py` confirmed net-zero new errors vs. HEAD (same
      pre-existing E501 at the line that shifted, no new findings).

## 5. Verify + archive
- [x] 5.1 `openspec validate --strict indicator-warmup-derive-from-1m`.
- [ ] 5.2 Boot smoke on the live host: no `indicator_warmup_api_error`; `indicator_warmup_derived_from_1m`
      present; `indicator_seeding_summary.unseeded` empty for the strangle configs. **(Next boot.)**
- [ ] 5.3 `openspec archive indicator-warmup-derive-from-1m`.
