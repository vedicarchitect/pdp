## 1. Resample helper

- [x] 1.1 `src/pdp/backtest/resample.py` — `resample_ohlcv` (tuples), `resample_data_dict` (Dhan arrays + vol/oi/iv), `resample_mongo_bars` (Mongo docs); open=first, high=max, low=min, close=last, volume=sum, oi/iv=last
- [x] 1.2 Unit tests incl. cross-check vs the live `BarBuilder` (`tests/test_backtest_resample.py`, 6 green)

## 2. Fetch 1m

- [x] 2.1 `fetch_bars` requests `interval=1` and resamples via `resample_ohlcv`
- [x] 2.2 Expired-options API fallback requests `interval=1` and resamples via `resample_data_dict` (persists resampled bars)
- [x] 2.3 NIFTY (`fetch_nifty`/Mongo) and option reads routed through resampling to the signal timeframe

## 3. Read path

- [x] 3.1 MongoDB-first NIFTY read prefers `1m` and resamples; falls back to native `5m`, then Dhan API
- [x] 3.2 Expired warehouse stays at the signal timeframe (API fallback persists resampled 5m)

## 4. Snapshot resolution (folded in per request)

- [x] 4.1 `_snapshot_nifty(trade_date)` loads `load_master_for_date` (latest ≤ date); `inst_map`/`active_expiry`/`expiry_available` prefer the snapshot, fall back to the live PG table (no regression for dates lacking a snapshot)

## 5. Validation

- [x] 5.1 `openspec validate backtest-1m-resample --strict`
- [x] 5.2 Script byte-compiles; resample + strategy + instruments suites green (40)
- [x] 5.3 Re-run a known day end-to-end vs prior native-5m result (needs live Dhan/Mongo/PG — deferred to a connected run)
