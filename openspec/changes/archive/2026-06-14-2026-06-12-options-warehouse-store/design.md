## Context / Goals

One warehouse, two producers (live feed + backfill), zero duplicates, fixed-contract identity,
trading-symbol stored. This change is storage-only; producers and readers are separate changes.

## Key Decisions

### D1 — Regular collection + unique index (not time-series)

**Decision:** `option_bars` is a **regular** MongoDB collection with a unique compound index on
`(underlying, expiry_date, strike, option_type, timeframe, ts)`. Writers use
`update_one(key, {"$setOnInsert": doc}, upsert=True)` (first-write-wins).

**Rationale:** Mongo **time-series collections cannot have a unique index**. With two independent
producers, DB-enforced uniqueness is the only robust "non-duplicate" guarantee. Scoped volume
(WEEK codes 1&2, ATM±10) is well under the full 74.7M, so losing native time-series compression is
acceptable. Alternatives (time-series + app dedup; two collections + merge-on-read) give weaker
guarantees and were rejected.

### D2 — Trading symbol stored; snapshot-preferred resolution

**Decision:** Every doc carries `trading_symbol`. `symbol_for(...)` builds the canonical symbol
deterministically; when a masters snapshot covers the contract's active window, the real
`SEM_TRADING_SYMBOL` and historical `security_id` are used instead.

**Rationale:** Enables fetching a fixed contract by symbol/security_id for positional backtests.
The abi `expired_options_ohlcv` has no symbol, so migrated rows must construct it.

## Failure Modes

| Risk | Mitigation |
| --- | --- |
| Upsert slowness at bulk load | Create the unique + read indexes before bulk load |
| Wrong `expiry_date` corrupts identity/dedup | Comes from the calendar change; validated downstream |
