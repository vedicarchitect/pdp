## 1. Standalone warehouser service

- [x] 1.1 `src/pdp/warehouse/__main__.py` + service module — own lifespan; connect Dhan feed
- [x] 1.2 Daily band roll — current + next weekly expiry (calendar); ATM from spot (`atm_strike`,
  NIFTY step 50); ATM±10 × {CE, PE}; resolve `security_id`s via instruments table / snapshot;
  subscribe (index + options on one connection)
- [x] 1.3 Contract-aware writer (mirror `market/bar_writer.py`) — `security_id`→contract, upsert
  `source=live` into `option_bars`
- [x] 1.4 Re-roll on ATM/expiry change without process restart
- [x] 1.5 Single-writer forward spot (sid 13 → `market_bars`)
- [x] 1.6 Ensure masters snapshot at session start (`instruments/snapshots.py`)

## 1b. Self-healing gap backfill

- [x] 1b.1 Extract reusable gap-fill core into `src/pdp/options/gap_backfill.py` (shared with
  `scripts/backfill_options_gap.py`); add `days_missing` coverage detection over a window
- [x] 1b.2 Periodic loop in the warehouser (`WAREHOUSE_GAP_CHECK_INTERVAL_HOURS`, default 4h) scans
  `WAREHOUSE_GAP_LOOKBACK_DAYS` (default 30) and backfills under-covered trade-days; runs off the
  event loop via `asyncio.to_thread`; toggle `WAREHOUSE_GAP_BACKFILL_ENABLED`
- [x] 1b.3 Offline tests (`tests/test_gap_backfill.py`) — band/day enumeration, gap detection,
  only-missing targeting

## 2. Validate + archive

- [x] 2.1 `openspec validate --strict 2026-06-12-options-warehouse-feed` → exits 0
- [ ] 2.2 Market-hours smoke: band subscriptions appear; `option_bars` rows land with `source=live`
  and correct resolved `expiry_date`/`strike`/`trading_symbol`
  (needs live Dhan creds + open market hours — cannot run in this environment)
- [ ] 2.3 `openspec archive 2026-06-12-options-warehouse-feed`
