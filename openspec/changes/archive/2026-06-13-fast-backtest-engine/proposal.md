## Why

The `option_bars` warehouse now holds multi-year NIFTY history, but a multi-expiry /
multi-month backtest cannot finish in under a minute. The cost is **Mongo round-trips, not
CPU**: the per-bar loop in `backtest_multiday.py` issues a fresh `option_bars.find().sort()`
on every strike change (`fetch_opt_fixed`), and when the exact strike is missing it fans out
up to `2 × WAREHOUSE_STRIKE_BAND` extra probes (`_nearest_strike_fallback`). NIFTY spot is
re-fetched per day. For a 3-month run this is thousands of queries.

This change replaces per-bar reads with a **batch chain pre-loader**: one indexed query per
expiry pulls the whole strike band into memory, and the fixed-strike reader (plus its
nearest-strike fallback) is served from RAM. The data-access path changes only — replayed
trades and P&L are byte-for-byte identical.

## What Changes

- **Batch chain loader** (`src/pdp/backtest/chain_loader.py`): one `option_bars` query per
  expiry over the `(underlying, expiry_date, option_type, ts)` index, grouped into an
  in-memory store keyed by `(trade_date, option_type) -> {strike: resampled_bars}`.
- **In-memory fixed-strike reader**: `fetch_opt_fixed` resolves exact strike, then nearest
  loaded strike within the band, from the store — no extra Mongo queries. The live-Dhan path
  remains only as a last resort for genuinely absent data.
- **Whole-range spot pre-load**: NIFTY `market_bars` for the entire backtest range loaded in
  one query and sliced per day, replacing the per-day fetch.
- **Performance instrumentation**: per-day and total `perf_counter` timing plus an
  `option_queries` counter logged via `structlog`, asserting the O(expiries) budget.

## Capabilities

### Modified Capabilities

- `backtest`: option-bar access becomes batch pre-loaded per expiry with an in-memory
  nearest-strike fallback and a stated performance budget.

## Impact

- New: `src/pdp/backtest/chain_loader.py`, `tests/backtest/test_chain_loader.py`
- Modified: `backtest_multiday.py` (data-access path only; results unchanged)
- No schema change; relies on the existing `idx_expiry_optype_ts` index.
- Depends on: `2026-06-12-options-backfill` (warehouse depth + coverage).
