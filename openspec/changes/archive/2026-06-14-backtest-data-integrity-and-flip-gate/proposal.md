## Why

`backtest_multiday.py` produces trade tables and P&L even on days where the NIFTU spot
`market_bars` series is incomplete or entirely absent. Auditing the 7-day window ending
2026-06-12, only **1 of 7 days** has complete NIFTU 1-minute spot data: three days have **zero**
spot bars (yet the backtest still printed full results), and 2026-06-12 has an **88-minute hole
(10:10→11:38)**. SuperTrend(3,1) computed on a gapped series freezes and cannot flip when it
should — e.g. the ~09:50 and ~10:55 flips visible on Kite never appear, so the backtest's first
trade is anchored to an unestablished opening direction rather than a real momentum change. The
result (PF 1.99 / +33,309 over the window) is therefore not trustworthy.

Dhan returns the missing data — verified live against an active data plan: NIFTU index 1m
(`security_id="13"`, `IDX_I`/`INDEX`) returns full days (374 bars) for every problem date,
including ones with zero local bars, back at least two years. The fix is to (1) backfill the
NIFTU spot history into `market_bars`, (2) backfill any absent option days using the existing
options gap tooling (which derives strikes from the index close, so spot must come first),
(3) make the backtest refuse to trade days that are still incomplete, and (4) anchor entries to
the first SuperTrend flip of the day rather than the cold-start direction.

## What Changes

- New `scripts/backfill_nifty_spot.py` — pulls NIFTU index 1m history from Dhan and upserts into
  `market_bars` (throttled, chunked, idempotent). Mirrors `scripts/backfill_options_gap.py`.
- Backtest data-completeness gate in `backtest_multiday.py` `simulate_day()` — validates the day's
  NIFTU 1m series and **skips incomplete days** with a `data_incomplete` status surfaced in the
  per-day header and final summary, instead of silently trading gapped data.
- Continuous cross-day SuperTrend warmup in `backtest_multiday.py` — each day's tracker is warmed
  with the prior trading session's bars so the indicator line is continuous across the day boundary
  (matching Kite/TradingView). Warmup bars are fed but not emitted, so the day's first flip is a
  genuine carried-over-direction change. This makes the early-morning flip appear (e.g. the 06-12
  GREEN gap-up flipping RED ~09:55) instead of the fresh cold-start seeding DOWN and missing it.
- Wait-for-first-flip entry discipline in `backtest_multiday.py` — entries are suppressed until the
  first SuperTrend flip after the session start each day.
- Existing `scripts/backfill_options_gap.py` is run (no code change) **after** the spot backfill to
  fill any absent option days over the same range.

## Capabilities

### Modified Capabilities
- `backtest`: Adds an input-data completeness gate (skip + `data_incomplete` status, never trade
  gapped spot data) and a wait-for-first-flip entry rule. Existing replay, indicator access, order
  simulation, and reporting are unchanged except for the new skip status in the summary.

## Impact

- New: `scripts/backfill_nifty_spot.py`.
- `backtest_multiday.py` — `simulate_day()` gains a completeness check + first-flip gate; the
  per-day and final summary printers gain a `data_incomplete` status row.
- Reuse (no change): `src/pdp/indicators/warmup.py` (`_fetch_from_dhan` index branch,
  `_persist_bars`), `pdp.options.gap_backfill.backfill_gaps` via `scripts/backfill_options_gap.py`,
  `src/pdp/backtest/resample.py` (`resample_ohlcv`), `SuperTrendTracker.flipped`.
- Data: `market_bars` gains backfilled NIFTU index 1m rows (idempotent upsert); `option_bars` gains
  any absent days. No schema changes.
- Tests: `tests/backtest/test_data_integrity.py` — completeness gate (complete day passes, gapped
  day skips, zero-bar day skips); first-flip gate (no entry before first flip, entry on/after it).
- Live trading behavior is unaffected (backtest-only).
