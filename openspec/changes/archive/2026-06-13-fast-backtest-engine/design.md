## Context

`backtest_multiday.py` replays NIFTY option strategies bar-by-bar against the `option_bars`
warehouse. With multi-year history now migrated, the goal is a multi-expiry / multi-month
backtest that finishes in **under one minute**. Profiling showed the cost is **MongoDB
round-trips, not CPU**:

- The per-bar inner loop calls `fetch_opt_fixed()` on every strike change, and each call
  issued a fresh `option_bars.find().sort("ts", 1)` for that single contract/day.
- When the exact strike was absent, `_nearest_strike_fallback` fanned out up to
  `2 × WAREHOUSE_STRIKE_BAND` (~20) extra `find().limit(1)` probes — so **missing data
  multiplied the query count**, coupling data completeness to speed.
- NIFTY spot (`market_bars`) was re-fetched once per simulated day.

For a 3-month run this is thousands of round-trips. CPU/resampling is negligible by
comparison, so the design target is to collapse query *count*, not to parallelise work.

## Goals / Non-Goals

**Goals:**
- Issue `O(number of expiries)` option-bar queries for a run, not `O(number of signal bars)`.
- Resolve the nearest-strike fallback entirely in memory — zero extra Mongo queries.
- Keep replayed trades, per-leg P&L, and summary totals **byte-for-byte identical** to the
  per-bar reader (data-access path change only).
- Emit timing + query-count instrumentation so the sub-minute budget is verifiable and
  regressions are caught.

**Non-Goals:**
- No multiprocessing / parallel day execution (in-process only; the bottleneck is I/O count,
  not CPU, and parallelism would complicate determinism for no proven gain).
- No pre-aggregated 5m rollup collection in Mongo (resample-on-load is cheap; a second
  collection adds write-path and consistency burden).
- No schema or index change — reuse the existing `idx_expiry_optype_ts`.
- No change to strategy logic, signal generation, or the live-Dhan code path.

## Decisions

**1. Batch pre-load one query per expiry, grouped in memory.**
`load_expiry_chain()` issues a single `option_bars.find` per expiry, filtered by
`underlying`, `expiry_date`, `option_type`, `timeframe`, and a `ts` range spanning that
expiry's trade-days, served by the `(underlying, expiry_date, option_type, ts)` index. Docs
are bucketed by `(IST trade_date, option_type, strike)` and each series is resampled once via
the existing `resample_ohlcv`. Result: `store[(trade_date, opt_type)] -> {strike: bars}`.
*Alternative considered:* one query per (day, strike) cached lazily — still `O(bars)` cold and
keeps the fallback fan-out. Rejected; batching by expiry is the natural grain because a weekly
expiry already groups all its trade-days and strikes.

**2. In-memory nearest-strike fallback.** `lookup_strike()` checks the exact strike, then
scans outward (`+step, -step, +2·step, …`) within `WAREHOUSE_STRIKE_BAND` over the
already-loaded chain. The live broker API is consulted only when *no* strike in the band was
pre-loaded. This removes the ~20-probe Mongo fan-out that made missing data expensive.

**3. Whole-range spot pre-load.** `preload_spot()` reads NIFTY `market_bars` for the entire
backtest range in one query, buckets by IST trade-date, and `_spot_1m_for_day` slices the
session window per day — replacing the per-day fetch (1 query instead of N).

**4. IST-date bucketing is exact.** The NSE session (≈03:45–10:00 UTC) falls on the same UTC
calendar date as its IST date, so bucketing a UTC `ts` by its IST-converted date is lossless;
no timezone-boundary split can occur within a session.

**5. Module-level store + preserved memo/return shape.** The store and counters live as
module globals populated by a pre-pass before the day loop; `fetch_opt_fixed` keeps its
`_bars` memo and `(strike, bars)` return contract so callers are unchanged.

## Risks / Trade-offs

- **Memory footprint of the whole band per expiry** → Bounded: one expiry × (2·band+1) strikes
  × 2 option types × one day's 1m bars, held only for the expiries in range; well within RAM
  for multi-month runs. Not a concern at NIFTY band sizes.
- **Silent divergence from the old reader** → Mitigated by a direct equivalence proof
  (836 real contracts of expiry 2025-06-05: 0 mismatches, 1 query) plus unit tests for
  grouping, IST bucketing, resample, and exact/nearest lookup.
- **Data gaps now surface as in-memory misses instead of Dhan fan-out** → Acceptable and
  intended; the live-Dhan last-resort path is retained, and coverage is tracked separately by
  the `2026-06-12-options-backfill` audit.

## Migration Plan

Pure code change, no data migration. The pre-pass is additive; the old per-bar query path is
replaced in place. Rollback is reverting `backtest_multiday.py` and removing
`src/pdp/backtest/chain_loader.py` — no persisted state is affected.

## Open Questions

None. Performance verified (3 months / 54 trading days = 13.0s, `option_queries=10`,
`spot_queries=1`) and correctness proven identical to the prior reader.
