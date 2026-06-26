# Warehouse Module

## Purpose

Bridges the **Abi DuckDB** (sibling project, historical options data) into PDP's **MongoDB `option_bars`** collection. Also runs the self-healing gap-backfill loop from Dhan API.

## Files

| File | Size | Role |
|------|------|------|
| `service.py` | 18.3 KB | `WarehouseService` — orchestrates the full migration/sync loop; reads Abi DuckDB, writes MongoDB |
| `writer.py` | 9.3 KB | `OptionBarWriter` — batch-upsert `option_bars` documents to MongoDB (first-write-wins) |
| `__main__.py` | 2.9 KB | CLI entry: `python -m pdp.warehouse --from <date> --to <date>` |
| `__init__.py` | 0.1 KB | Exports `WarehouseService` |

## Data Flow

```
Abi DuckDB (../Abi/data/historicaldata/nifty.db)
  → WarehouseService.migrate(from, to)
      → reads option OHLCV rows by date + strike + expiry
      → OptionBarWriter.write_batch()
          → MongoDB option_bars (upsert, first-write-wins)
              index: (security_id, expiry, strike, option_type, ts) unique
```

## MongoDB `option_bars` Schema

```python
{
  "security_id": str,
  "underlying": str,       # e.g. "NIFTY", "BANKNIFTY"
  "expiry": date,
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
| `ABI_NIFTY_DUCKDB` | `../Abi/data/historicaldata/nifty.db` | Path to sibling project DB |
| `ABI_CUTOFF_DATE` | `2026-05-23` | Gap-fill starts from this date |
| `EXPIRY_CACHE_PATH` | `data/expiry/nifty_expiries.json` | Built via OI-reset detection |
| `WAREHOUSE_STRIKE_BAND` | 10 | ATM ± N strikes stored |
| `WAREHOUSE_STRIKE_STEP` | 50 | Strike increment (50 for NIFTY; 100 for BANKNIFTY/SENSEX) |
| `WAREHOUSE_INCLUDE_MONTHLY` | False | Include monthly expiry |
| `WAREHOUSE_GAP_BACKFILL_ENABLED` | True | Auto gap-heal loop |
| `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS` | 4.0 | How often to scan for gaps |
| `WAREHOUSE_GAP_LOOKBACK_DAYS` | 30 | Rolling window for gap scan |
| `NSE_HOLIDAYS_JSON` | `data/calendars/nse_holidays_2023_2026.json` | Trading-day calendar |

## Run the migration manually

```bash
# Migrate full historical window from Abi DuckDB
uv run python -m pdp.warehouse --from 2024-01-01 --to 2026-05-23

# Backfill spot (index 1m bars from Dhan)
python scripts/backfill_spot.py --from 2026-02-09 --to 2026-06-12 --only-missing
```

## Active Specs

`2026-06-12-options-warehouse-store`, `2026-06-12-options-warehouse-feed` (in-flight).
`historical-data-migration`, `mongo-store` (archived specs — reference for schema decisions).
