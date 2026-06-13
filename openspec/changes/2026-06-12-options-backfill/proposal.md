## Why

The `option_bars` warehouse needs historical depth to be useful for backtests. We have a validated
source — the abi-project DuckDB `expired_options_ohlcv` (74.7M NIFTY rows, 2020-08-03 → 2026-05-22,
1-minute, actual `strike_price`, `oi`, `iv`) — plus the live Dhan API for the tail. This change
backfills the warehouse from both, migrates historical NIFTY spot, and proves integrity.

## What Changes

- **Abi DuckDB → `option_bars` migrator**: read-only over `nifty.db`, scoped to `WEEK` codes 1&2 and
  the ATM±10 ladder (CE+PE; monthly behind a flag), resolving real `expiry_date` (expiry calendar)
  and `trading_symbol`, upserting with `source=abi`. Idempotent and restartable.
- **Dhan gap-fill**: cover the range after the Abi cutoff to the present not already captured by the
  live feed — by `security_id` where the contract is still active, by the rolling-option API +
  calendar where expired — upserting with `source=dhan_api`.
- **NIFTY spot migrator**: load Abi `nifty_spot_1m`/`spot_1m` + the Dhan `nifty_spot.duckdb` into
  `market_bars` (security_id `13`, `1m`), deduplicated by `ts`.
- **Validation gates**: reconcile counts, prove zero duplicates, and sanity-check OHLC,
  `expiry_date`, and label↔strike consistency.

## Capabilities

### New Capabilities

- `historical-data-migration`: Abi options migrator, Dhan gap-fill, spot migrator, and validation
  gates for the options warehouse.

## Impact

- New: `scripts/migrate_abi_options.py`, `scripts/backfill_options_gap.py`,
  `scripts/migrate_spot_bars.py`, `scripts/validate_options_warehouse.py`
- Deprecated: `scripts/backfill_expired_options.py` (superseded)
- `market_bars` gains historical NIFTY spot rows (no schema change). External read-only source: abi
  DuckDB (never mutated).
- Depends on: `2026-06-12-nifty-expiry-calendar` and `2026-06-12-options-warehouse-store`.
