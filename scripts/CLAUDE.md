# scripts/ — Operational & Maintenance Scripts

All scripts run from the **repo root** with `uv run python scripts/<name>.py` or via `task`.
See [README.md](README.md) for full arg reference.

## Quick reference

| Task alias | Script | Purpose |
|-----------|--------|---------|
| `task backfill:spot` | `backfill_nifty_spot.py` | NIFTY 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:options` | `backfill_options_gap.py` | Option OHLCV → `option_bars`. `--from --to --codes --band --only-missing` |
| `task backfill:expired` | `backfill_expired_options.py` | Expired-contract bars |
| `task backfill:vix` | `backfill_vix.py` | India VIX 1m → `market_bars` (sid 21; intraday history from ~Aug-2021). `--from --to --resolve --only-missing` |
| `task audit:strangle` | `audit_strangle_data.py` | Per-year spot/options/VIX coverage for the directional-strangle backtest |
| `task migrate:abi` | `python -m pdp.warehouse` | Abi DuckDB → MongoDB migration |
| `task audit:coverage` | `audit_options_coverage.py` | Coverage gap audit by date+strike |
| `task validate:warehouse` | `validate_options_warehouse.py` | Integrity: missing days, bad prices, OI |
| `task validate:migration` | `verify_nifty_migration.py` | Verify Abi → MongoDB completeness |
| `task expiry` | `expiry_analysis.py` | Read-only expiry analysis (NIFTY+BANKNIFTY+SENSEX, max-pain/PCR/VIX/OI walls). `--symbol --expiry` |
| `task oi:track` | `expiry_analysis.py --track` | OI snapshot tracker, ATM±N vs morning baseline → JSONL (always) + Mongo `oi_snapshots` TS + Redis `oi:{sym}`/`oi.events.{sym}`. `--strikes --interval --event-threshold-pct --store mongo,redis\|none` |
| `task monitor` | `monitor.pl` | Perl live monitor (read-only Redis+API) |
| `task reset-paper` | `reset_paper.py` | ⚠️ Clears paper orders/trades/positions from PG |

## Data pipeline order

1. `task backfill:spot` (spot must exist before options derivation)
2. `task backfill:options`
3. `task audit:coverage` + `task validate:warehouse`

## Archive

`archive/` — archived scripts. Do not use as templates.
Backtest runners moved to `backtest/` (repo root): use `task backtest` / `task backtest:sweep` / `task backtest:compare`.
