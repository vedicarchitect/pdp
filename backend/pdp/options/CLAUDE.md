# Options Module

## Files

| File | Size | Role |
|------|------|------|
| `poller.py` | 10 KB | `OptionsChainPoller` — fetches chain snapshots from Dhan API; persists to MongoDB `option_chains`; **live-only** |
| `hub.py` | 2.2 KB | `OptionsHub` — WS fan-out for chain updates |
| `greeks.py` | 3.8 KB | Greeks computation (Delta, Gamma, Theta, Vega, IV) via Black-Scholes |
| `warehouse.py` | 4.6 KB | Chain data access helpers for backtest/warehouse reads |
| `dhan_client.py` | 3.8 KB | Thin Dhan API wrapper for option chain fetch |
| `gap_backfill.py` | 13.3 KB | Self-healing backfill — scans rolling window for missing `option_bars` days from Dhan |
| `analytics.py` | 1.5 KB | Chain analytics helpers (PCR, max OI strike, etc.) |
| `routes.py` | 3.5 KB | REST: `/options/chain`, `/options/analytics` |
| `ws.py` | 1.9 KB | `/ws/options` WebSocket endpoint |

## Start Condition

`OptionsChainPoller` only starts when `LIVE=1` AND `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` set.
In paper/dev mode: chain data is read from MongoDB warehouse (pre-loaded historical snapshots).

## MongoDB `option_chains` Schema

```python
{
  "underlying": str,       # "NIFTY", "BANKNIFTY"
  "expiry": date,
  "strike": int,
  "option_type": "CE"|"PE",
  "ts": datetime,          # snapshot timestamp (UTC)
  "ltp": Decimal,
  "oi": int, "volume": int,
  "iv": float,
  "delta": float, "gamma": float, "theta": float, "vega": float
}
```

TTL: `OPTIONS_CHAIN_TTL_DAYS` (default 7). Index: `(underlying, expiry, strike, option_type, ts)`.

## Settings

| Key | Default |
|-----|---------|
| `OPTIONS_POLL_INTERVAL_SECONDS` | 30 |
| `OPTIONS_RISK_FREE_RATE` | 0.065 |
| `OPTIONS_UNDERLYINGS` | `["NIFTY","BANKNIFTY"]` |
| `OPTIONS_CHAIN_TTL_DAYS` | 7 |

## Gap Backfill

`gap_backfill.py` runs every `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS=4.0` hours. Scans `WAREHOUSE_GAP_LOOKBACK_DAYS=30` for missing `option_bars` trade-days. Uses `NSE_HOLIDAYS_JSON` for trading-day calendar. Needs live Dhan creds. First-write-wins (non-duplicate).

## Active Specs

`2026-06-12-options-warehouse-feed`, `2026-06-12-options-warehouse-store`, `options-analytics-tools` (in-flight).
