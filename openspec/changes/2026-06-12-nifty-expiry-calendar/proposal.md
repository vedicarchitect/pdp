## Why

Both the live options warehouser and the historical backfill must key every option bar by its
**real contract** `(underlying, expiry_date, strike, option_type)`. That requires resolving
`(trade_date, expiry_flag, expiry_code) → real expiry_date` across the full history — during which
NIFTY's weekly-expiry weekday changed (Thursday → Wednesday → Tuesday) and individual expiries
shifted for exchange holidays. Hardcoded weekday/holiday math is brittle and silently wrong across
those regime changes.

This change provides a NIFTY expiry calendar derived **empirically** from the data itself, so it is
correct by construction regardless of rule changes. It is the shared foundation the warehouse,
migration, and backtest changes build on.

## What Changes

- **OI-reset expiry detection**: detect real expiry dates from the abi-project DuckDB
  `expired_options_ohlcv` — on rollover the first bar of D+1 is a fresh contract with near-zero OI,
  so `first_bar_oi[D+1] / first_bar_oi[D] < ~0.55` flags a true expiry day. (Approach ported from
  `Abi/src/data/bootstrap_expiry_history.py`.)
- **Cached calendar**: detection runs once and persists `data/expiry/nifty_expiries.json`; runtime
  consumers read the cache with no DuckDB dependency.
- **`resolve_expiry(trade_date, flag, code)`**: the `code`-th `flag` expiry on or after
  `trade_date` (the expiry day itself counts as code 1), plus a hook to merge forward expiries from
  the live instruments table.

## Capabilities

### New Capabilities

- `nifty-expiry-calendar`: empirical resolution of real NIFTY weekly/monthly expiry dates.

## Impact

- New: `src/pdp/instruments/expiry_calendar.py`, `tests/test_expiry_calendar.py`
- New settings: `ABI_NIFTY_DUCKDB`, `EXPIRY_CACHE_PATH` (`src/pdp/settings.py`)
- New artifact: `data/expiry/nifty_expiries.json` (built from the read-only abi DuckDB)
- No API or DB schema changes
