# scripts/ — Operational & Maintenance Scripts

All scripts run from the **repo root** with `uv run python scripts/<name>.py` or via `task`.
See [README.md](README.md) for full arg reference.

## Quick reference

| Task alias | Script | Purpose |
|-----------|--------|---------|
| `task backfill:nifty` | `backfill_spot.py` | NIFTY 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:banknifty` | `backfill_spot.py` | BANKNIFTY 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:sensex` | `backfill_spot.py` | SENSEX 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:options` | `backfill_options_gap.py` | NIFTY option OHLCV → `option_bars`. `--from --to --codes --band --only-missing` |
| `task backfill:options:banknifty` | `backfill_options_gap.py` | BANKNIFTY option OHLCV → `option_bars`. Same flags as `backfill:options` |
| `task backfill:options:sensex` | `backfill_options_gap.py` | SENSEX option OHLCV → `option_bars`. Same flags as `backfill:options` |
| `task backfill:expired` | `backfill_expired_options.py` | Expired-contract bars |
| `task backfill:vix` | `backfill_vix.py` | India VIX 1m → `market_bars` (sid 21; intraday history from ~Aug-2021). `--from --to --resolve --only-missing` |
| `task backfill:levels` | `backfill_levels.py` | Daily + weekly standard/Camarilla/Fibonacci levels → `index_levels`. `--symbol --from --to --only-missing --dry-run` |
| `task backfill:levels:all` | `backfill_levels.py` | Same but runs NIFTY + BANKNIFTY + SENSEX sequentially. |
| `task audit:strangle` | `audit_strangle_data.py` | Per-year spot/options/VIX coverage for the directional-strangle backtest |
| `task audit:coverage` | `audit_options_coverage.py` | Coverage gap audit by date+strike |
| `task validate:warehouse` | `validate_options_warehouse.py` | Integrity: missing days, bad prices, OI |
| `task expiry` | `expiry_analysis.py` | Read-only expiry analysis (NIFTY+BANKNIFTY+SENSEX, max-pain/PCR/VIX/OI walls). `--symbol --expiry` |
| `task oi:track` | `expiry_analysis.py --track` | OI snapshot tracker, ATM±N vs morning baseline → JSONL (always) + Mongo `oi_snapshots` TS + Redis `oi:{sym}`/`oi.events.{sym}`. `--strikes --interval --event-threshold-pct --store mongo,redis\|none` |
| `task monitor` | `monitor.pl` | Perl live monitor (read-only Redis+API) |
| `task reset-paper` | `reset_paper.py` | ⚠️ Clears paper orders/trades/positions from PG |
| `task backtest:ingest` | `ingest_backtest_run.py` | Ingest a `backtest/runs/<id>/` folder into the Mongo backtest warehouse. `--run-dir` or `--wf-csv + --run-id`; `--bulk-dir backtest/runs [--remove]` ingests every folder, verifies each against Mongo, and only removes local folders confirmed present |

## Data pipeline order

1. `task backfill:nifty` / `backfill:banknifty` / `backfill:sensex` (spot must exist before options derivation)
2. `task backfill:options` / `backfill:options:banknifty` / `backfill:options:sensex`
3. `task audit:coverage` + `task validate:warehouse`
4. `task backfill:levels:all` (requires step 1 to be complete; computes daily+weekly levels from spot bars)

## Archive

`archive/` — archived scripts. Do not use as templates.
Backtest runners moved to `backtest/` (repo root): use `task backtest` / `task backtest:sweep`. Backtest-vs-paper
comparison is now `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` (or the `/backtest:vs-paper` skill), not a
Taskfile task — the old single-day `backtest:compare` CLI is retired.
