# Design — strategy-execution-panel

## Locked decisions (2026-06-30)

1. **4hr timeframe dropped** — `BarAggregator` only produces 1m/5m/15m/30m/1H/1D. Matrix uses
   `5m/15m/30m/1H/1D`. 4H aggregation deferred.
2. **Weekly Camarilla → add `1w` bars** — currently `get_pivots(sid,"1w")` is always `None`
   (`directional_strangle.py:589-594` logs `cam_weekly_missing`). Adding `1w` makes it real.
3. **Greeks/OI/PCR → read `option_chains` snapshots + run poller by default** — paper sessions need
   realtime chain data, so the poller is decoupled from `LIVE`.
4. **Levels persisted in MongoDB** (not Postgres) — see below.

## Monitor payload — `GET /api/v1/strangle/monitor`

One JSON doc (async, read-only, Decimals serialised to float):

```jsonc
{
  "indices": {
    "NIFTY":     { "spot": 24500.0, "future": 24560.0 },   // future null if futures_security_id unset
    "BANKNIFTY": { "spot": 0, "future": null },
    "SENSEX":    { "spot": 0, "future": null }
  },
  "groups": [                                              // grouped by underlying
    { "underlying": "NIFTY",
      "legs": [
        { "security_id":"...", "opt_type":"CE", "strike":24700, "lots":1, "is_hedge":false,
          "entry_price":120.0, "entry_time":"2026-06-30T09:35:00+05:30", "entry_reason":"NEUTRAL@0.10",
          "ltp":95.0, "mtm":1875.0,
          "delta":-0.32, "vega":8.1, "gamma":0.0007, "theta":-5.2,        // non-hedge active strikes only
          "oi":1820000, "pcr":0.92, "oi_change_day":140000 }
      ],
      "totals": { "day_realized":0, "day_unrealized":1875.0, "day_pnl":1875.0 } }
  ],
  "totals":  { "day_realized":0, "day_unrealized":1875.0, "day_pnl":1875.0 },
  "status":  { "bucket":"NEUTRAL", "score":0.10, "done_for_day":false,
               "started_at":"...", "n_open_shorts":2, "n_open_hedges":2, "n_open_momentum":0 },
  "recent_events": [ /* last N from _activity deque — closed legs + exit reasons */ ],
  "indicators": {
    "13": {  // per sid: 3 indices + active non-hedge strike sids
      "tf": { "5m": {...}, "15m": {...}, "30m": {...}, "1H": {...}, "1D": {...} },  // ema9/20/50/100, st{val,dir}, psar
      "camarilla_daily":  { "pp":..,"r3":..,"r4":..,"s3":..,"s4":.. },
      "camarilla_weekly": { "pp":..,"r3":..,"r4":..,"s3":..,"s4":.. },
      "period": { "pdh":..,"pdl":..,"pwh":..,"pwl":.. }
    }
  }
}
```

Reuse: `_get_strangle(request)` (`pdp/strategy/routes.py:58`); Redis `ltp:{sid}` for spot/future;
`pdp/options/routes.py` `_latest_snapshot` + `pdp/options/analytics.compute_pcr`; engine getters
`get_ema/get_psar/get_pivots/get_period_levels` + `engine.get` (SuperTrend). Pivot/period levels are
per-session constants — compute once. Spot sids: NIFTY 13, BANKNIFTY 25, SENSEX 51.

Refresh: Flutter REST-polls every ~2s (no dedicated WS channel — deferred). Day-start OI = earliest
`option_chains` snapshot of today for that underlying/strike.

## Levels warehouse storage — MongoDB `index_levels`

**Why Mongo, not Postgres**: rule #8 splits Mongo (time-series bars/chains) from PG (ACID orders).
Levels are derived per-session reference data computed *from* `market_bars` and consumed by backtest +
ML which already read Mongo → co-locate. Schemaless docs make future ML level-families migration-free.
Volume is tiny (~5k rows for 5yr × 3 indices × daily+weekly). Use a **regular** collection (NOT
time-series) because we upsert by unique key and Mongo TS collections reject upsert
(`backfill_spot.py:161`).

Indexes: unique `(security_id, period, session_date)`; secondary `(underlying, period, session_date)`.

```jsonc
{
  "schema_version": 1,
  "security_id": "13", "underlying": "NIFTY",
  "period": "daily",                         // "weekly" now; "monthly" later, no migration
  "session_date": "2026-06-30",              // the session these levels APPLY to
  "source": { "h":24650, "l":24380, "c":24500, "window_start":"2026-06-27", "window_end":"2026-06-27" },
  "standard":  { "pp":..,"r1":..,"r2":..,"r3":..,"s1":..,"s2":..,"s3":.. },
  "camarilla": { "pp":..,"r3":..,"r4":..,"s3":..,"s4":.. },
  "fibonacci": { "pp":..,"r1":..,"r2":..,"r3":..,"s1":..,"s2":..,"s3":.. },
  "levels": { },                             // OPEN map for future families (cpr/vwap_bands/murrey/sd_zones)
  "computed_at": "2026-06-30T03:46:00Z"
}
```

PDH/PDL = daily `source.h/l`; PWH/PWL = weekly `source.h/l` — period levels fall out for free.

`pdp/indicators/levels_store.py::LevelsStore` reuses `pivots._compute_pivots(h,l,c,date)`
(`pivots.py:40`, already does standard+Camarilla+Fibonacci). Methods: `upsert`, `get`,
`range(sid,period,start,end)` (backtest/ML feed), `to_feature_rows()` (nested→flat for ML DataFrames),
`compute_daily`, `compute_weekly`. Daily lifespan/`pdp/jobs` task persists the current session at
startup/boundary; weekly recomputed each Monday. Backfill `scripts/backfill_levels.py` reuses
`trading_days()/holidays()` from `pdp.options.gap_backfill`.

## Alternatives rejected

- **Greeks on-demand via Black-Scholes** (`greeks.py`) instead of snapshots — rejected; user chose
  snapshots + default-on poller for true realtime parity with live.
- **Levels in Postgres** — rejected; cross-DB joins to bars, migration per new ML family, no ACID need.
- **WebSocket monitor channel** — deferred; 2s REST poll is adequate for a monitor.
