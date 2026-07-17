# indicator-warmup-derive-from-1m

## Why

The `DH-905` warmup error has been "fixed" repeatedly (`indicator-history-depth`,
`dhan-same-day-data`, `bar-session-anchoring`) yet keeps returning. On 2026-07-17 it was live again:

```
{"security_id":"51","timeframe":"30m","mongo_count":893,"target":1000,"event":"indicator_warmup_fetching_from_api"}
{"resp":"...'error_code':'DH-905'...'Data for Intraday Charts can be fetched for 90 days at a time'...","event":"indicator_warmup_api_error"}
{"security_id":"51","timeframe":"1H",...,"event":"indicator_warmup_api_error"}
```

Root cause: `warmup.py::_fetch_from_dhan` issues a **single, un-chunked** `intraday_minute_data`
call spanning the *entire* EMA200 lookback — `lookback_days("30m", 1000) ≈ 108` calendar days,
`lookback_days("1H", 1000) ≈ 200`. Dhan caps intraday history at **90 days per request**, so every
30m/1H EMA200 top-up is rejected and the tracker stays short (893/1000) and shows `--`.

It keeps recurring because each prior fix patched a *symptom* (depth calc, same-day candle, session
anchoring) while leaving the fragile design in place: **startup self-heals a data gap by calling a
rate-limited, 90-day-capped, token-expiry-prone live intraday API on the boot critical path.** The
1-minute series in `market_bars` is already backfilled ~5 years deep, and the live `BarAggregator`
already rolls higher timeframes from 1m using a session-anchored bucket function — so warmup never
needed the intraday API for 15m/30m/1H at all.

A ready-made 90-day chunker (`scripts/backfill_spot.py::_chunks`) and a 1m→higher-TF rollup
(`scripts/oneoff/rebuild_market_bars.py::rollup_bars`, used by `scripts/backfill_market_bars.py`)
already exist elsewhere; the warmup path simply never adopted either.

## What Changes

- **Derive derivable timeframes (15m/30m/1H) from the 1m series in Mongo, not the intraday API.**
  When a higher-TF store is short, warmup reads the 1m series and rolls it up via the same
  session-anchored `_bar_boundary` the live `BarAggregator` uses, drops any still-forming final
  bucket (`bar_is_complete`), persists the derived bars (delete-then-insert), and seeds from them.
  `5m` keeps its existing direct path (its 200-floor window is never over 90 days).
- **Chunk any remaining Dhan intraday fallback by ≤90 calendar days.** When 1m coverage is itself
  missing, `_fetch_from_dhan` now loops `intraday_minute_data` over ≤90-day windows and concatenates
  — a window wider than the cap no longer fails whole with DH-905, and one bad chunk is logged and
  skipped rather than aborting the fetch. Daily (`historical_daily_data`) is unaffected (not capped).
- **Keep depth guaranteed out-of-band.** `scripts/backfill_market_bars.py` (+ `task backfill:daily`)
  already derives 15m/30m/1H from 1m and should run as a scheduled pre-session job so `market_bars`
  is deep before boot; the existing `indicator_seeding_summary` boot line already surfaces any
  residual gap loudly. (Scheduling is an ops step; the code no longer *depends* on it.)

## Impact

- Affected specs: `indicator-warmup` (top-up source of truth + chunked fallback).
- Affected code: `backend/pdp/indicators/warmup.py` — new `_derive_bars_from_1m`,
  `_ninety_day_chunks`, `_replace_derived_bars`; `_warm_one` prefers 1m-derivation for 15m/30m/1H
  before the Dhan fallback; `_fetch_from_dhan` chunks intraday by 90 days. No schema/migration
  changes. 5m and daily paths unchanged.
