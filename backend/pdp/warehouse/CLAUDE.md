# Warehouse Module

## Purpose

Maintains PDP's **MongoDB `option_bars`** collection for one or more configured underlyings via a
live tick feed (real-time) and a self-healing gap-backfill loop (Dhan REST API).

## Files

| File | Size | Role |
|------|------|------|
| `service.py` | ~9 KB | `WarehouseService` — multi-underlying tick subscription + band roll + gap-heal |
| `writer.py` | ~9 KB | `OptionBarWriter` — per-underlying async writer; routes to `option_bars` or `market_bars` |
| `__main__.py` | ~2 KB | Entry: `python -m pdp.warehouse` |
| `__init__.py` | 0.1 KB | Exports `WarehouseService` |

## Data Flow

```
Dhan WS feed (one connection, multiple sids)
  → WarehouseService._consume_ticks()
      → BarAggregator (1m bars)
          → self._writers[security_id]        # O(1) routing table
              → OptionBarWriter.enqueue(bar)
                  ├─ index sid  → market_bars (spot bar)
                  └─ option sid → option_bars (upsert, first-write-wins)

Gap-heal loop (periodic, per-underlying):
  → run_gap_backfill(underlying=..., underlying_sid=..., strike_step=...)
      → MongoDB option_bars (upsert)
```

## Multi-underlying support

`UNDERLYING_REGISTRY` in `service.py` defines the supported set:

| Underlying | IDX_I SID | Strike step |
|------------|-----------|-------------|
| NIFTY      | 13        | 50          |
| BANKNIFTY  | 25        | 100         |
| SENSEX     | 51        | 100         |

Which underlyings get warehoused is **not a setting** (since `bias-input-completeness`,
2026-07-12) — `WarehouseService(underlyings=...)` takes an explicit list, computed by
`pdp.strategy.registry.strategy_underlyings(strategies_dir)` (the union of every loaded
strategy YAML's `params.underlying`) in both `pdp/warehouse/__main__.py` and
`scripts/backfill_market_bars.py`. Add an underlying by adding/editing a strategy YAML
with `params.underlying: BANKNIFTY` — no `.env` edit, no code change. Unsupported entries
still raise `ValueError` at startup before any Dhan connection is opened.

## MongoDB `option_bars` Schema

```python
{
  "security_id": str,
  "underlying": str,       # e.g. "NIFTY", "BANKNIFTY"
  "expiry_date": date,
  "strike": int,
  "option_type": "CE"|"PE",
  "timeframe": "1m",
  "ts": datetime,          # bar open (UTC)
  "open": Decimal, "high": Decimal, "low": Decimal, "close": Decimal,
  "volume": int, "oi": int
}
```

## Settings

| Key | Default | Notes |
|-----|---------|-------|
| `EXPIRY_CACHE_PATH` | `data/expiry/nifty_expiries.json` | NIFTY expiry calendar |
| `BANKNIFTY_EXPIRY_CACHE_PATH` | `data/expiry/banknifty_expiries.json` | BANKNIFTY expiry calendar |
| `SENSEX_EXPIRY_CACHE_PATH` | `data/expiry/sensex_expiries.json` | SENSEX expiry calendar |
| `WAREHOUSE_STRIKE_BAND` | 10 | ATM ± N strikes stored per underlying |
| `WAREHOUSE_STRIKE_STEP` | 50 | Strike increment for NIFTY (per-underlying in registry for others) |
| `WAREHOUSE_INCLUDE_MONTHLY` | False | Include monthly expiry |
| `WAREHOUSE_GAP_BACKFILL_ENABLED` | True | Auto gap-heal loop |
| `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS` | 4.0 | How often to scan for gaps |
| `WAREHOUSE_GAP_LOOKBACK_DAYS` | 30 | Rolling window for gap scan |
| `NSE_HOLIDAYS_JSON` | `data/calendars/nse_holidays_2021_2026.json` | Trading-day calendar |

## Run gap-backfill manually

```bash
# Backfill options gap for a date range
uv run python -m pdp.warehouse --from 2026-06-01 --to 2026-06-25

# Backfill spot (NIFTY 1m bars from Dhan)
python scripts/backfill_spot.py --from 2026-06-01 --to 2026-06-25 --only-missing
```
