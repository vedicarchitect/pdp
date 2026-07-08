# scripts/ — Operational & Maintenance Scripts

All scripts run from the **repo root** with `uv run python scripts/<name>.py` or via `task`.

## Everyday backfill

Full history (5yr spot/options/levels + VIX since ~Aug-2021) is already backfilled. Day to
day, just run:

```
task backfill:daily              # tops up the last 7 days, all 3 indices, --only-missing
task backfill:daily -- --from 2026-06-01   # wider catch-up window if a day was missed
```

This runs, in dependency order, for NIFTY+BANKNIFTY+SENSEX: `backfill_spot.py` →
`backfill_options_gap.py` → `backfill_vix.py` (index-independent) →
`backfill_levels.py` (needs spot written first). Every step passes `--only-missing`, so
re-running it is always safe/idempotent — it only writes days that are actually short of
bars. Use the per-symbol/per-purpose tasks below only for one-off backfills (e.g. a fresh
multi-year history, or re-running just one index/step).

## Quick reference

| Task alias | Script | Purpose |
|-----------|--------|---------|
| `task backfill:daily` | spot+options+vix+levels | Everyday top-up for all 3 indices, see above. `--from --to` |
| `task backfill:nifty` | `backfill_spot.py` | NIFTY 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:banknifty` | `backfill_spot.py` | BANKNIFTY 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:sensex` | `backfill_spot.py` | SENSEX 1m spot → `market_bars`. `--from --to --only-missing --dry-run` |
| `task backfill:options:nifty` | `backfill_options_gap.py` | NIFTY option OHLCV → `option_bars`. `--from --to --codes --band --only-missing` |
| `task backfill:options:banknifty` | `backfill_options_gap.py` | BANKNIFTY option OHLCV → `option_bars`. Same flags as `backfill:options:nifty` |
| `task backfill:options:sensex` | `backfill_options_gap.py` | SENSEX option OHLCV → `option_bars`. Same flags as `backfill:options:nifty` |
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

## Data pipeline order (for one-off/manual runs — `backfill:daily` already does this)

1. `task backfill:nifty` / `backfill:banknifty` / `backfill:sensex` (spot must exist before options derivation)
2. `task backfill:options:nifty` / `backfill:options:banknifty` / `backfill:options:sensex`
3. `task audit:coverage` + `task validate:warehouse`
4. `task backfill:levels:all` (requires step 1 to be complete; computes daily+weekly levels from spot bars)

## Archive

`archive/` — archived scripts. Do not use as templates.
Backtest runners moved to `backtest/` (repo root): use `task backtest` / `task backtest:sweep`. Backtest-vs-paper
comparison is now `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` (or the `/backtest:vs-paper` skill), not a
Taskfile task — the old single-day `backtest:compare` CLI is retired.
