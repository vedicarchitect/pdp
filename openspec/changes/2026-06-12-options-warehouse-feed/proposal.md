## Why

Backfill seeds history, but the warehouse must also grow forward every trading day. We want a
process that streams the current/next-week NIFTY option band live and persists 1-minute fixed-strike
bars into `option_bars` — independent of the trading app's uptime and strategy concerns — so the
warehouse stays current with no manual backfill.

## What Changes

- **Standalone warehouser service** (`python -m pdp.warehouse`): own lifespan and market-feed
  connection. At session start (and on ATM/expiry roll) it computes the current + next weekly band
  (ATM±10 × CE/PE, monthly optional), resolves each strike to a `security_id`, subscribes via the
  Dhan feed, builds 1-minute bars, and upserts fixed-strike contracts into `option_bars`
  (`source=live`) using the contract-aware writer.
- **Masters snapshot trigger**: ensures `data/masters/<date>.csv` exists at session start so expired
  contracts' symbol + historical `security_id` stay recoverable.
- **Single spot writer**: the warehouser owns forward NIFTY-index capture into `market_bars` (sid 13)
  to avoid time-series duplicates from two producers.
- **Self-healing gap backfill**: a periodic loop (default every 4h) scans the rolling last-30-days
  for under-covered `option_bars` trade-days and auto-backfills them from Dhan — sharing the gap-fill
  core with the one-shot script and running off the event loop so the live feed is never blocked.

## Capabilities

### New Capabilities

- `options-warehouse-feed`: standalone live options warehouser (band roll, subscribe, 1m persist,
  masters snapshot).

## Impact

- New: `src/pdp/warehouse/` (service entrypoint + contract-aware writer),
  `src/pdp/options/gap_backfill.py` (reusable gap-fill core).
- New settings: `WAREHOUSE_STRIKE_BAND`, `WAREHOUSE_STRIKE_STEP`, `WAREHOUSE_INCLUDE_MONTHLY`
  (already added in the calendar change's settings block); `WAREHOUSE_GAP_BACKFILL_ENABLED`,
  `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS`, `WAREHOUSE_GAP_LOOKBACK_DAYS`, `NSE_HOLIDAYS_JSON`.
- Reuses `market/dhan_ws.py` (`DhanTickerAdapter`), `market/bars.py` (`BarAggregator`/`BarBuilder`),
  `instruments/snapshots.py`. No DB schema change.
- Refactors `scripts/backfill_options_gap.py` to share `pdp.options.gap_backfill`.
- Depends on: `2026-06-12-nifty-expiry-calendar` and `2026-06-12-options-warehouse-store`.
