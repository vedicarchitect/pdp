# PDP — Backend dev index

All Python lives here. Run tooling via the root `Taskfile.yml` (sets `dir: backend`) or
`uv run ...` from this directory. Package is `pdp` (import as `pdp.*`). `.env` is here.

## Dev-activity → minimal context (load only these)

| If you're working on… | Read only |
|------------------------|-----------|
| Directional strangle (core) | `pdp/strategies/` (strangle), `pdp/signals/`, `pdp/backtest/strangle_config.py`, `backtest/strangle_run.py` |
| Strangle backtest tuning | `backtest/strangle_run.py`, `backtest/configs/strangle_*.yaml`, `pdp/backtest/` |
| Backtest engine / sweeps | `pdp/backtest/`, `backtest/run.py`, `backtest/sweep_all.py` |
| Options warehouse / backfill | `pdp/warehouse/`, `pdp/options/`, `scripts/backfill_*.py`, `scripts/audit_*.py` |
| Orders / broker / execution | `pdp/orders/`, `pdp/portfolio/`, `pdp/risk/` |
| Live strategy host / paper | `pdp/strategy/`, `pdp/market/`, `pdp/indicators/` |
| Events / alerts feed | `pdp/events/`, `pdp/alerts/` |
| Indicators | `pdp/indicators/` (compute once; never recompute in strategies) |
| ML signals | `pdp/ml/`, `scripts/ml_train.py` |
| Migrations | `alembic/`, `alembic.ini` |
| Broker account/report sync (chunk 2–3) | `pdp/portfolio/`, `pdp/orders/`, `pdp/db/`, `dhanhq` skill |
| Unified log pipeline / OpenSearch | `pdp/observability/` (+ `CLAUDE.md` there), `pdp/logging.py`, `pdp/settings.py` (`OPENSEARCH_*`), `infra/compose/docker-compose.yml` |

## Module map (`backend/pdp/*` — each folder has its own CLAUDE.md)

| Path | Domain |
|------|--------|
| `pdp/main.py` | App factory + lifespan wiring |
| `pdp/settings.py` | All env vars (pydantic-settings); `.env` in `backend/` |
| `pdp/alerts/` | Alert rules, evaluator, WS hub |
| `pdp/backtest/` | BacktestEngine, sim, commissions, `strangle_config.py` |
| `pdp/cli/` | Click CLI entry point |
| `pdp/db/` | SQLAlchemy base + async session |
| `pdp/events/` | Live event publisher: realtime monitoring + WS/push |
| `pdp/housekeeping/` | Async housekeeping tasks + REST routes |
| `pdp/indicators/` | IndicatorEngine, SuperTrend, warmup |
| `pdp/instruments/` | Dhan scrip master, expiry calendar |
| `pdp/jobs/` | Async job runner + WS progress stream |
| `pdp/journal/` | Fill recording, daily stats |
| `pdp/market/` | Tick feed, bar agg, WS hub |
| `pdp/ml/` | Offline LightGBM training + online inference |
| `pdp/mongo/` | MongoDB client + collection init |
| `pdp/options/` | Chain poller, Greeks, gap_backfill |
| `pdp/orders/` | Paper + Dhan broker, order router |
| `pdp/portfolio/` | MTM P&L, kill-switch |
| `pdp/positional/` | Swing F&O + equity positions |
| `pdp/risk/` | KillSwitchService, hard-cap |
| `pdp/signals/` | Bias-scoring engine (directional strangle): multi-TF votes → buckets → PE:CE |
| `pdp/strategies/` | Strategy implementations |
| `pdp/strategy/` | StrategyHost, BaseStrategy ABC |
| `pdp/warehouse/` | Options warehouse — multi-underlying feed + self-healing gap-backfill |
| `pdp/observability/` | Unified OpenSearch log pipeline (chunk 5): structlog processor, indexer, typed sinks, ingest endpoint, routes — see `pdp/observability/CLAUDE.md` |

## Non-pdp dirs

| Path | Domain |
|------|--------|
| `backtest/` | Runnable backtest scripts + `configs/*.yaml` (`run.py`, `strangle_run.py`, `compare.py`) |
| `strategies/` | Strategy YAML configs (auto-loaded) |
| `scripts/` | Operational scripts (Taskfile-wired); `scripts/oneoff/` = run-once graveyard |
| `alembic/` | DB migrations (`alembic.ini` here) |
| `tests/` | pytest suite |
| `data/` | Local masters/calendars/snapshots (git-ignored) |

## Notes
- `task lint`/`task test` carry **pre-existing** debt (267 ruff items, 27 test failures e.g.
  `PositionState` needing `strategy_id`) unrelated to layout — clean up in a dedicated change.
- Some `backtest/configs/strangle_*.yaml` carry a stale `vix_gate_enabled` key (VIX gate was
  removed) — they error until updated; the default `StrangleConfig()` runs clean.
