## 1. MongoDB collection

- [x] 1.1 Add `_ensure_expired_option_bars` time-series collection in `src/pdp/mongo/collections.py`
- [x] 1.2 Wire it into `init_collections`
- [x] 1.3 Add `get_expired_option_bars_collection` accessor

## 2. Backfill command

- [x] 2.1 Create `scripts/backfill_expired_options.py` with CLI args (months, flag, codes, strikes, types, interval)
- [x] 2.2 Chunk the date range into ≤30-day windows and call `expired_options_data` with `expiry_code=1`, 0.25s pause
- [x] 2.3 Unwrap nested `data["data"]["ce"|"pe"]` payload before side selection (`_extract_side`)
- [x] 2.4 Parse bars to UTC `ts` docs keeping volume/oi/iv (`_parse_bars`)
- [x] 2.5 Idempotent insert: dedup against existing `ts` normalized to aware UTC
- [x] 2.6 Ensure the time-series collection exists before insert (`_ensure_collection`)

## 3. Backtest read path

- [x] 3.1 Rewrite `fetch_opt_expired` to read `expired_option_bars` first (`_expired_from_mongo`)
- [x] 3.2 Fall back to live API with `expiry_code=1` and corrected unwrap order on cache miss
- [x] 3.3 Persist API-fetched bars back into the warehouse (`_persist_expired`), guarded so it never auto-creates a non–time-series collection

## 4. Verification

- [x] 4.1 Confirm `expired_option_bars` is created as a time-series collection
- [x] 4.2 Backfill smoke test inserts bars; re-run inserts zero (idempotent)
- [x] 4.3 Full strategy-minimal backfill (~12 months) populates the warehouse (109k bars)
- [x] 4.4 Backtest on an expired day (2026-06-02) prices legs from MongoDB and produces trades
