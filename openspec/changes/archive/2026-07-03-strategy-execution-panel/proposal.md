## Why

We are about to start live paper sessions for the directional strangle and have no single place to
watch it execute. The backend `state()` snapshot lacks per-leg entry time/reason and Greeks, the
options chain poller only runs with `LIVE=1` (so paper sessions get no realtime Greeks/OI/PCR), weekly
Camarilla is never computed (no `1w` bars), and there is no Flutter execution monitor. Separately, pivot
levels are recomputed live every run and never persisted, so they cannot be referenced historically or
fed to backtests/ML.

## What Changes

- **Realtime strangle monitor**: `GET /api/v1/strangle/monitor` returns index/future LTPs (NIFTY/
  BANKNIFTY/SENSEX), all legs grouped by underlying with entry time/reason + per-strike Greeks/OI/PCR/
  ΔOI, totals, status, and an indicator matrix (EMA 9/20/50/100, ST(10,2), PSAR across 5m/15m/30m/1H/1D
  + daily/weekly Camarilla + PDH/PDL/PWH/PWL). New Flutter "Strategy Execution" tab in the Manage hub.
- **Options poller default-on**: poller starts on Dhan creds alone (not gated by `LIVE`), giving paper
  sessions realtime chain data. Read-only; gated by new `OPTIONS_POLLER_ENABLED` (default true).
- **Weekly bars + weekly Camarilla**: `BarAggregator` gains a `1w` timeframe so `get_pivots(sid,"1w")`
  yields weekly Camarilla.
- **`OpenLeg` metadata**: `entry_time` + `entry_reason` added and exposed via `state()`.
- **Persisted levels warehouse**: new Mongo `index_levels` collection storing daily + weekly standard/
  Camarilla/Fibonacci pivots (one-time per session), a daily compute job, a 5-year backfill from spot
  `market_bars`, an ML-expandable schema, and a read API.

## Capabilities

### New Capabilities

- `strategy-execution-monitor`: realtime directional-strangle monitor endpoint + Flutter panel.
- `levels-warehouse`: persisted daily/weekly pivot/Fibonacci levels in MongoDB for back-reference,
  backtest, and ML, with a 5-year backfill.

### Modified Capabilities

- `options-warehouse-feed`: options poller starts on Dhan creds alone (paper-safe, read-only).
- `indicator-suite`: `1w` bar aggregation + weekly Camarilla pivots.
- `directional-strangle`: `OpenLeg` carries `entry_time`/`entry_reason`, surfaced in `state()`.

## Impact

Depends on `market-data`, `indicator-suite`, `options-analytics`, `directional-strangle`,
`strangle-execution-console`. Adds Mongo collection `index_levels`; adds `task backfill:levels`. No
schema change to PostgreSQL. Flutter Manage hub gains a 5th tab.
