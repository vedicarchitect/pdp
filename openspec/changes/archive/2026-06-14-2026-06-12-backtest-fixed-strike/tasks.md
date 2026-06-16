## 1. Fixed-strike read path

- [x] 1.1 `backtest_multiday.py` — target strike from spot (`atm_strike`/`otm_strike`) + `expiry_date`
  (calendar); read `option_bars` fixed contract; `resample_ohlcv` to the signal timeframe
- [x] 1.2 Nearest-available-strike fallback within the band; log the substitution
- [x] 1.3 Positional path: read a held contract by fixed key (by `trading_symbol`/`security_id`
  where Dhan supports it)
- [x] 1.4 `fetch_nifty` reads `market_bars` (sid 13) first, Dhan live fallback
- [x] 1.5 Retire the `expired_option_bars` read
  (`_expired_meta`/`_expired_from_mongo`/`_persist_expired`)

## 2. Validate + archive

- [x] 2.1 `openspec validate --strict 2026-06-12-backtest-fixed-strike` → exits 0
- [x] 2.2 Multi-day backtest over the migrated April-2026 window prices from the fixed strike series
  (logs show real strikes hit, `[expiry:calendar]` resolution, and warehouse-miss fallback to Dhan);
  4 profit days, 108 trades. (Deliberate missing-strike fallback path exists in `_nearest_strike_fallback`.)
- [ ] 2.3 `openspec archive 2026-06-12-backtest-fixed-strike` (after a non-creds sanity review)
