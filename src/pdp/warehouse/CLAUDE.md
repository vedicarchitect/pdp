# Warehouse Module

## Purpose

Maintains PDP's **MongoDB `option_bars`** collection via a self-healing gap-backfill loop from the Dhan API. Historical data was seeded in a one-time migration (archived); this module now owns ongoing freshness only.

## Files

| File | Size | Role |
|------|------|------|
| `service.py` | 18.3 KB | `WarehouseService` — orchestrates the gap-backfill sync loop; reads Dhan API, writes MongoDB |
| `writer.py` | 9.3 KB | `OptionBarWriter` — batch-upsert `option_bars` documents to MongoDB (first-write-wins) |
| `__main__.py` | 2.9 KB | CLI entry: `python -m pdp.warehouse --from <date> --to <date>` |
| `__init__.py` | 0.1 KB | Exports `WarehouseService` |

## Data Flow

```
Dhan API (intraday option OHLCV)
  → WarehouseService.gap_backfill(from, to)
      → OptionBarWriter.write_batch()
          → MongoDB option_bars (upsert, first-write-wins)
```

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
| `EXPIRY_CACHE_PATH` | `data/expiry/nifty_expiries.json` | Pre-built JSON expiry calendar |
| `WAREHOUSE_STRIKE_BAND` | 10 | ATM ± N strikes stored |
| `WAREHOUSE_STRIKE_STEP` | 50 | Strike increment (50 for NIFTY; 100 for BANKNIFTY/SENSEX) |
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
