## 1. Expiry calendar

- [x] 1.1 `src/pdp/instruments/expiry_calendar.py` — OI-reset detection over the abi DuckDB
  (`detect_expiries`, `build_cache`); ported from `Abi/src/data/bootstrap_expiry_history.py`.
  No hardcoded weekday/holiday rules.
- [x] 1.2 `NiftyExpiryCalendar.load()` + `resolve_expiry(trade_date, flag, code)` — bisect lookup,
  expiry day counts as code 1; forward-expiry merge hook.
- [x] 1.3 New settings `ABI_NIFTY_DUCKDB`, `EXPIRY_CACHE_PATH` (`src/pdp/settings.py`).
- [x] 1.4 Build cache `data/expiry/nifty_expiries.json` (171 weekly / 59 monthly detected).
- [x] 1.5 `tests/test_expiry_calendar.py` — 8 tests (weekday-agnostic, holiday shift, regime change,
  out-of-range, edge cases); all pass.

## 2. Validate + archive

- [x] 2.1 `openspec validate --strict 2026-06-12-nifty-expiry-calendar` → exits 0
- [ ] 2.2 `openspec archive 2026-06-12-nifty-expiry-calendar` (after dependent changes confirm the
  interface; calendar is already implemented and tested)
