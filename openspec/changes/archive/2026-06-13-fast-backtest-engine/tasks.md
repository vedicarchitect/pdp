## 1. Batch chain loader

- [x] 1.1 `src/pdp/backtest/chain_loader.py` — `load_expiry_chain(col, expiry_date, trade_dates,
  *, tf_min)`: one `option_bars.find` per expiry over `idx_expiry_optype_ts`; group docs by
  `(IST trade_date, option_type, strike)`; resample each series once via `resample_ohlcv`; return
  `store[(trade_date, opt_type)] -> {strike: bars}` + query count. Pure function, no globals.
  Plus `lookup_strike()` for exact/nearest in-memory resolution.
- [x] 1.2 Unit test `tests/backtest/test_chain_loader.py` — grouping, IST-day bucketing, resample,
  exact/nearest lookup, empty-input no-query (fake-collection; 4 tests pass).

## 2. Wire into backtest_multiday.py

- [x] 2.1 `preload_chains(days)`: group days by resolved expiry, `load_expiry_chain` once per
  expiry into module-level `_chain_store`; `_chain_queries` counter.
- [x] 2.2 `fetch_opt_fixed` serves exact then in-memory nearest-strike via `lookup_strike`;
  live-Dhan kept as last resort; `_bars` memo + return shape preserved.
- [x] 2.3 `preload_spot(days)` + `_spot_1m_for_day`: one `market_bars` query for the range,
  bucketed by IST trade-date, filtered to the session window per day.
- [x] 2.4 `perf_counter` timing + `option_queries`/`spot_queries` counters; `backtest_complete`
  log line at run end.

## 3. Verify

- [x] 3.1 Regression: loader proven byte-identical to the old direct-Mongo reader over 836 real
  contracts of expiry 2025-06-05 (0 mismatches, 1 query).
- [x] 3.2 Performance: 60-day / 3-month 2025 run → `elapsed_s=13.0`, `option_queries=10`
  (= 10 expiries), `spot_queries=1`; zero Dhan fallbacks (PF 9.84, 1876 trades).
- [x] 3.3 `openspec validate --strict fast-backtest-engine` → exits 0.
- [ ] 3.4 `openspec archive fast-backtest-engine` after verification.
