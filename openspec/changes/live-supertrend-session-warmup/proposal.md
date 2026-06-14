## Why

The live/paper `IndicatorEngine` keeps one `SuperTrendTracker` per `(security_id, timeframe)`
that is created once and never reset, so while the process runs continuously SuperTrend is
correctly **continuous across days** — matching Kite/TradingView. The risk is **process restart
during the trading day**: `warm_up_indicator_engine` seeds the fresh tracker from a fixed
**8-hour wall-clock** lookback (`LOOKBACK_HOURS = 8` in `src/pdp/indicators/warmup.py`).

The overnight gap between NIFTY sessions is ~17.75h (15:30 IST close → 09:15 IST open), far longer
than 8h. So for **any** intraday restart the 8h window lands *after* the prior session's close and
pulls **same-day bars only** — verified for restarts at 09:20/10:30/12:00/14:00/15:00 IST, all
same-day-only. SuperTrend then cold-starts: it seeds direction DOWN via the first-bar tie-break
(`close <= final_upper`) regardless of the true carried-over trend, and can flip incorrectly until
enough same-day bars accumulate. A 09:20 restart seeds with ~5 minutes of data. The `MIN_BARS = 10`
Dhan fallback only tops up to ~10 same-day bars; it does not reach the prior session either.

This is the exact cold-start artifact just fixed in the backtest (change
`backtest-data-integrity-and-flip-gate` added a prior-session warmup). Live/paper must mirror it so
a mid-day restart does not desynchronise the live SuperTrend from the chart and from the backtest.

## What Changes

- Replace the fixed 8-hour wall-clock lookback in `warm_up_indicator_engine` with a
  **session-aware lookback**: seed from the start of the most recent prior trading session,
  walking back over weekend/holiday gaps (no-data days), so the prior session's bars are always
  present on any restart time.
- Raise the warmup target so, when Mongo is thin, the Dhan fallback fetches enough history to cover
  a **full prior session** (not just `MIN_BARS = 10`), guaranteeing the carried-over direction is
  established before the first live bar.
- No change to `IndicatorEngine` (its persistent-tracker design is already correct); the fix is
  confined to how the tracker is seeded at startup.

## Capabilities

### Added Capabilities
- `indicator-warmup`: Defines how the live indicator engine is seeded on startup so SuperTrend is
  continuous with the prior session regardless of restart time, keeping live/paper signals aligned
  with the chart and the backtest.

## Impact

- `src/pdp/indicators/warmup.py` — session-aware lookback + larger warmup target; `_fetch_from_mongo`
  window and the Dhan-fallback trigger adjusted. `src/pdp/main.py` warmup call site unchanged.
- Reuse: trading-day/holiday helpers (e.g. `pdp.options.gap_backfill.trading_days` / `holidays`) for
  walking back over non-trading days; `pdp.backtest.resample` if resampling the seed is needed.
- Live/paper behavior: a mid-day restart now seeds SuperTrend from the prior session (continuous),
  matching Kite and the backtest; a continuously-running process is unaffected.
- Tests: warmup seeds across a weekend/holiday gap; a mid-day restart yields the carried-over
  direction (not a cold-start DOWN seed).
- Paper-first and live-routing rules are untouched (warmup is read-only history seeding).
