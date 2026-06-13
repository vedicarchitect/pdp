## 1. Scrip-name / symbol resolution

- [x] 1.1 `src/pdp/instruments/symbols.py` — `symbol_for(...)` builds Dhan `SEM_TRADING_SYMBOL`
  format `NIFTY-Mmm{YYYY}-{STRIKE}-{CE|PE}` (verified against real `scrips_compact.csv`)
- [x] 1.2 `resolve_symbol(...)` — snapshot-preferred: when `data/masters/<date>.csv` covers the
  contract, returns the real symbol + historical `security_id` (`SymbolInfo`); else constructed
- [x] 1.3 `tests/test_symbols.py` — symbol format + constructed/snapshot resolution (4 tests, pass)

## 2. Unified `option_bars` collection

- [x] 2.1 `src/pdp/mongo/collections.py::_ensure_option_bars` — **regular** collection + **unique**
  index `uq_contract_ts (underlying, expiry_date, strike, option_type, timeframe, ts)` + read
  indexes `idx_expiry_optype_ts`, `idx_strike_optype_ts`; wired into `init_collections`;
  `get_option_bars_collection` added
- [x] 2.2 Contract-aware upsert helper — `src/pdp/options/warehouse.py`:
  `build_option_bar_doc`, `option_bar_upserts` (first-write-wins `$setOnInsert`),
  `upsert_option_bars_sync`/`_async` (pymongo + motor)
- [x] 2.3 `tests/test_option_bars_collection.py` — real-Mongo dedup proof: same `(contract, ts)`
  from two producers → one doc, first-write-wins; distinct contracts both inserted (skips if no
  local Mongo). Plus `test_mongo.py` unit test asserting regular collection + unique index.

## 3. Validate + archive

- [x] 3.1 `openspec validate --strict 2026-06-12-options-warehouse-store` → exits 0
- [ ] 3.2 `openspec archive 2026-06-12-options-warehouse-store`
