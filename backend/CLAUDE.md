# PDP — Backend dev index

All Python lives here. Run tooling via the root `Taskfile.yml` (sets `dir: backend`) or
`uv run ...` from this directory. Package is `pdp` (import as `pdp.*`). `.env` is here.

## Dev-activity → minimal context (load only these)

| If you're working on… | Read only |
|------------------------|-----------|
| Directional strangle (core) | `pdp/strategies/directional_strangle.py`, `pdp/signals/bias.py`, `backtest/configs/strangle_*.yaml` |
| Strangle backtest tuning | `backtest/configs/strangle_*.yaml`, `pdp/backtest/`, `backtest/run.py` |
| Backtest engine / sweeps | `pdp/backtest/`, `backtest/run.py`, `backtest/sweep_all.py`; DB-first warehouse + skills — see `pdp/backtest/CLAUDE.md` |
| Options warehouse / backfill | `pdp/warehouse/`, `pdp/options/`, `scripts/backfill_*.py`, `scripts/audit_*.py` |
| Orders / broker / execution | `pdp/orders/`, `pdp/portfolio/`, `pdp/risk/` |
| Live strategy host / paper | `pdp/strategy/`, `pdp/market/`, `pdp/indicators/` |
| Events / alerts feed | `pdp/events/`, `pdp/alerts/` |
| Indicators | `pdp/indicators/` (compute once; never recompute in strategies) |
| ML signals | `pdp/ml/`, `scripts/ml_train.py` |
| Migrations | `alembic/`, `alembic.ini` |
| Broker account/report sync (chunk 2–3) | `pdp/portfolio/`, `pdp/orders/`, `pdp/db/`, `dhanhq` skill |
| Unified log pipeline / OpenSearch | `pdp/observability/` (+ `CLAUDE.md` there), `pdp/logging.py`, `pdp/settings.py` (`OPENSEARCH_*`), `infra/compose/docker-compose.yml` |
| Dashboard feeds (chunk 6) | `pdp/intel/` (poller, sources, sections, routes, dashboard_routes), `pdp/options/fii_dii.py` (`NseFIIDIISource`), `pdp/settings.py` (`INTEL_*`, `MCX_*_SECURITY_ID`, `VIX_SECURITY_ID`) |

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
| `pdp/intel/` | Dashboard market-intel feeds: `poller.py` (off-hot-path refresher, gated `INTEL_ENABLED`), `sources/{global_market,news,sentiment}.py` (yfinance/feedparser/vaderSentiment, each Protocol+Stub+real impl), `sections.py` (shared section builders), `routes.py` (standalone `/api/v1/intel/*`), `dashboard_routes.py` (composed `GET /api/v1/dashboard`) |
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

## Context: Memory & OpenSpec

For **live-to-backtest parity** issues, see:
- **Indicator warmup gaps** → `memory/execution_console_accuracy.md` (EMA200 seeding, RSI/PSAR divergence)
- **Live execution vs backtest** → `memory/live_backtest_parity.md` (18/21 tasks done, 3 deploy-day verifies remain)
- **Directional strangle specs** → `memory/directional_strangle.md` (canonical config, known gaps, lot history)

For implementation specs, start at:
- **Strategy registry** → `openspec/specs/strategy-registry/spec.md`
- **Indicator suite** → `openspec/specs/indicators/spec.md`
- **Market feed** → `openspec/specs/market-feed/spec.md`

## Notes
- `task test` is green: `1010 passed, 2 xfailed` (2026-07-10, see `test-suite-baseline-green`).
  The two `xfail(strict=True, ...)` markers (`tests/strategies/test_leg_rehydration.py`,
  `tests/strategies/test_event_taxonomy.py`) are intentional — they name a real, in-flight
  OpenSpec change as owner and must start failing the suite the moment they start passing
  unexpectedly. `task test` exits non-zero on any real failure; there is no standing debt to route
  around.
- The three canonical strangle configs (`strangle_nifty_hedged.yaml`, `strangle_banknifty_hedged.yaml`,
  `strangle_sensex_hedged.yaml`) are clean — no stale keys. Old inactive configs moved to `strategies/inactive/`.
