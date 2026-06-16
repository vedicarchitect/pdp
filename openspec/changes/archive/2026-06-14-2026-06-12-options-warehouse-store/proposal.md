## Why

The current expired-option store (`expired_option_bars`) is a time-series collection keyed by an
ATM-relative `strike_label` with no real strike, so a "held" leg drifts across strikes and the same
bar can be written twice by different producers. We need one warehouse that both a live feed and a
backfill can write into, keyed by the **real fixed contract**, with duplicates made structurally
impossible and the contract's **trading symbol** stored for fixed-contract fetches.

This change delivers the storage foundation only: the collection, its unique index, the
contract-aware upsert writer, and the symbol resolver. The producers (live feed, backfill) and the
backtest read land in their own changes.

## What Changes

- **`option_bars` collection**: a regular (non-time-series) MongoDB collection keyed by
  `(underlying, expiry_date, strike, option_type, timeframe, ts)` with a **unique** index — the DB
  itself rejects duplicate bars regardless of which producer writes. Read indexes by expiry and by
  strike. Each doc carries `trading_symbol`, optional `security_id`, `oi`, `iv`, `strike_label`,
  `expiry_flag`, and `source`.
- **Contract-aware upsert writer**: first-write-wins (`$setOnInsert`) so live + backfill are both
  idempotent against the same warehouse.
- **Scrip-name resolution**: `symbol_for(underlying, expiry_date, strike, option_type)` builds the
  canonical Dhan trading symbol; where a masters snapshot exists, the real symbol + historical
  `security_id` are preferred. This is what later enables fetching a fixed contract by
  symbol/security_id instead of the drifting rolling-option API.

## Capabilities

### New Capabilities

- `options-warehouse`: unified `option_bars` collection, real-contract identity, unique-index dedup,
  contract-aware upsert, and trading-symbol storage.

## Impact

- New: `src/pdp/instruments/symbols.py`
- Modified: `src/pdp/mongo/collections.py` (`_ensure_option_bars` + indexes + getter + upsert helper;
  wired into `init_collections`)
- New Mongo collection `option_bars` (regular, unique-indexed). No PostgreSQL schema change.
- Depends on: `2026-06-12-nifty-expiry-calendar` (real `expiry_date` for the contract key).
