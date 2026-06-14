# scripts/ — Operational & Maintenance Scripts

All scripts are run from the **repo root** with `uv run python scripts/<name>.py` (or via `task`).

## Backtest & Analysis

| Script | Task alias | Purpose |
|--------|-----------|---------|
| `backtest_compare.py` | — | Backtest vs paper-journal comparison for a single IST date. `--date YYYY-MM-DD` |
| `backtest_sweep.py` | `task backtest` (via root `backtest_multiday.py`) | Multi-config parameter sweep (ST period/tf/moneyness grid). Part of `configurable-strategy-backtest-sweep` change. |

## Data Pipeline & Backfill

| Script | Purpose |
|--------|---------|
| `backfill_nifty_spot.py` | Backfill NIFTY 1m spot bars (`market_bars`) from Dhan for a date range. `--from`, `--to`, `--only-missing` |
| `backfill_options_gap.py` | Backfill missing `option_bars` dates from Dhan for a date range. |
| `backfill_expired_options.py` | Backfill expired-contract option bars (historical). |
| `migrate_abi_options.py` | One-time: migrate NIFTY options OHLCV from Abi DuckDB → MongoDB `option_bars`. |
| `migrate_spot_bars.py` | One-time: migrate NIFTY spot bars into MongoDB `market_bars`. |

## Validation & Audit

| Script | Purpose |
|--------|---------|
| `audit_options_coverage.py` | Audit coverage of `option_bars` by date+strike — identifies gaps. |
| `validate_options_warehouse.py` | Validate warehouse integrity: checks for missing days, bad prices, OI anomalies. |
| `verify_nifty_migration.py` | Verify that the Abi→MongoDB migration is complete and consistent. |

## Operations

| Script | Task alias | Purpose |
|--------|-----------|---------|
| `monitor.pl` | `task monitor` | Live strategy monitor (Perl, read-only). Polls Redis + FastAPI every second. |
| `reset_paper.py` | `task reset-paper` | Clear paper orders/trades/positions from PostgreSQL and reset ID sequences. ⚠️ Destructive. |

## Archive

See [`archive/README.md`](archive/README.md) for one-time debug scripts from specific sessions.
