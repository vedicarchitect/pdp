## Why

The backtest currently prices expired-option legs from `expired_option_bars` by an ATM-relative
rolling label, which drifts across strikes intraday and cannot represent a held position. With the
`option_bars` warehouse keyed by the real fixed contract, the backtest can price each leg from the
actual `(expiry_date, strike, option_type)` series — stable within a day and across multi-day holds
— enabling realistic intraday and positional backtests.

## What Changes

- **Fixed actual-strike read** in `backtest_multiday.py`: derive the target strike from spot
  (`atm_strike` + the strategy's OTM offset) and the `expiry_date` from the expiry calendar, then
  read that exact contract from `option_bars`, resampled to the signal timeframe.
- **Nearest-strike fallback**: when the exact strike has no bars for a day, price from the nearest
  available strike in the warehoused band before any live call ("as far as possible").
- **Positional path**: read a held contract by its fixed key (and, where Dhan supports it, by
  `trading_symbol`/`security_id`) across the days it is held.
- **Deprecate** the `expired_option_bars` ATM-label read; the deprecated collection receives no new
  writes.

## Capabilities

### Modified Capabilities

- `backtest`: option legs are priced from `option_bars` by fixed actual strike + expiry, with a
  nearest-strike fallback and a positional by-symbol path.
- `expired-option-bars`: superseded by `option_bars`; retained read-only and deprecated.

## Impact

- Modified: `backtest_multiday.py` (replace `_expired_meta`/`_expired_from_mongo`/`_persist_expired`
  with the fixed-strike `option_bars` read; `fetch_nifty` reads `market_bars` first)
- Depends on: `2026-06-12-options-warehouse-store` (collection); data from
  `2026-06-12-options-backfill`. No DB schema change.
