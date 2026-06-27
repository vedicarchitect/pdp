# PDP — Agent Rules & Index

Source of truth: `openspec/specs/<cap>/spec.md` · In-flight: `openspec/changes/<id>/`
Full stack/layout: [`openspec/project.md`](openspec/project.md)
**How to run anything**: [`RUNBOOK.md`](RUNBOOK.md)

## ⛔ Non-Negotiables

1. **Spec-first** — `openspec new change <id>` → implement → `openspec archive <id>`
2. **Paper-first** — live orders only when `LIVE=1` + `BROKER=dhan` + creds. Default = paper.
3. **One mutation/route** — endpoints do one thing.
4. **Universal indicators** — `IndicatorEngine` computes once; strategies consume, never recompute.
5. **Latency** — tick→WS p99 ≤ 50ms. No blocking on hot path.
6. **structlog only** — no `print()` / `rich` in core modules.
7. **Settings via `get_settings()`** — never `os.environ` directly.
8. **DB split** — PostgreSQL = orders/trades/positions (ACID). MongoDB = bars/chains (time-series). Redis = hot cache/pub-sub.
9. **Speed, quality, clean UI are core — no compromise.** Every data path must be fast (no N+1, no blocking on hot path). Every UI surface must be pixel-consistent and production-grade. Architecture decisions must optimise for these three properties first.
10. **Frontend changes require Playwright verification.** After any frontend change, run `cd frontend && npx playwright test` before marking tasks done. Add e2e tests for new routes and components to `frontend/e2e/`.

## Key Commands

```bash
task dev          # uvicorn :8000 --reload
task db:up / db:migrate / db:down / db:tools
task test / lint / fmt / typecheck
task monitor      # perl scripts/monitor.pl
task reset-paper  # ⚠️ clears paper DB
task backtest     # 7-day per-trade detail (BACKTEST_DEFAULT_CONFIG)
task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30
task backtest:sweep  -- --st "3,1;10,2" --tf "5,15" --moneyness "1,0,-1" [--days N]
task backfill:nifty     -- --from YYYY-MM-DD [--only-missing] [--dry-run]
task backfill:banknifty -- --from YYYY-MM-DD [--only-missing]
task backfill:sensex    -- --from YYYY-MM-DD [--only-missing]
task backfill:options -- [--from] [--only-missing]
task backtest:compare -- [--date YYYY-MM-DD]
task openspec:list / openspec:validate -- <id> / openspec:archive -- <id>
```

## Module Index (each folder has its own CLAUDE.md)

| Path | Domain |
|------|--------|
| `src/` | Python package root → [`CLAUDE.md`](src/CLAUDE.md) |
| `src/pdp/main.py` | App factory + lifespan wiring |
| `src/pdp/settings.py` | All env vars (pydantic-settings) |
| `src/pdp/alerts/` | Alert rules, evaluator, WS hub → [`CLAUDE.md`](src/pdp/alerts/CLAUDE.md) |
| `src/pdp/backtest/` | BacktestEngine, sim, commissions → [`CLAUDE.md`](src/pdp/backtest/CLAUDE.md) |
| `src/pdp/cli/` | Click CLI entry point → [`CLAUDE.md`](src/pdp/cli/CLAUDE.md) |
| `src/pdp/db/` | SQLAlchemy base + async session → [`CLAUDE.md`](src/pdp/db/CLAUDE.md) |
| `src/pdp/events/` | Live event publisher: position-aware realtime monitoring + WS/push → [`CLAUDE.md`](src/pdp/events/CLAUDE.md) |
| `src/pdp/indicators/` | IndicatorEngine, SuperTrend, warmup → [`CLAUDE.md`](src/pdp/indicators/CLAUDE.md) |
| `src/pdp/instruments/` | Dhan scrip master, expiry calendar → [`CLAUDE.md`](src/pdp/instruments/CLAUDE.md) |
| `src/pdp/journal/` | Fill recording, daily stats → [`CLAUDE.md`](src/pdp/journal/CLAUDE.md) |
| `src/pdp/market/` | Tick feed, bar agg, WS hub → [`CLAUDE.md`](src/pdp/market/CLAUDE.md) |
| `src/pdp/ml/` | Offline LightGBM training + online inference (candlestick-ML signals) → [`CLAUDE.md`](src/pdp/ml/CLAUDE.md) |
| `src/pdp/mongo/` | MongoDB client + collection init → [`CLAUDE.md`](src/pdp/mongo/CLAUDE.md) |
| `src/pdp/options/` | Chain poller, Greeks, gap_backfill → [`CLAUDE.md`](src/pdp/options/CLAUDE.md) |
| `src/pdp/housekeeping/` | Async housekeeping tasks + REST routes |
| `src/pdp/jobs/` | Async job runner: submit/track tasks + WS progress stream |
| `src/pdp/ml/` | Offline LightGBM training + online candlestick-pattern inference → [`CLAUDE.md`](src/pdp/ml/CLAUDE.md) |
| `src/pdp/orders/` | Paper + Dhan broker, order router → [`CLAUDE.md`](src/pdp/orders/CLAUDE.md) |
| `src/pdp/portfolio/` | MTM P&L, kill-switch → [`CLAUDE.md`](src/pdp/portfolio/CLAUDE.md) |
| `src/pdp/positional/` | Swing F&O + equity positions → [`CLAUDE.md`](src/pdp/positional/CLAUDE.md) |
| `src/pdp/risk/` | KillSwitchService, hard-cap → [`CLAUDE.md`](src/pdp/risk/CLAUDE.md) |
| `src/pdp/signals/` | Pure bias-scoring engine (directional strangle): multi-TF votes → 7 buckets → PE:CE ratio + VIX gate |
| `src/pdp/strategies/` | Strategy implementations (Python) → [`CLAUDE.md`](src/pdp/strategies/CLAUDE.md) |
| `src/pdp/strategy/` | StrategyHost, BaseStrategy ABC → [`CLAUDE.md`](src/pdp/strategy/CLAUDE.md) |
| `src/pdp/warehouse/` | Options warehouse — multi-underlying live feed + self-healing gap-backfill → [`CLAUDE.md`](src/pdp/warehouse/CLAUDE.md) |
| `alembic/` | DB migrations (alembic.ini stays at root) → [`CLAUDE.md`](alembic/CLAUDE.md) |
| `docs/` | Supplementary feature docs → [`CLAUDE.md`](docs/CLAUDE.md) |
| `frontend/` | Vite + React 19 + TanStack + hand-rolled CVA UI kit → [`CLAUDE.md`](frontend/CLAUDE.md) |
| `backtest/` | Runnable backtest scripts + YAML configs → [`CLAUDE.md`](backtest/CLAUDE.md) |
| `backtest/run.py` | Canonical multi-day runner: single-config detail or grid sweep |
| `backtest/strangle_run.py` | Directional-strangle runner (bias-driven option selling; `--hedge`, `--trace`) |
| `backtest/compare.py` | Single-day backtest vs paper journal |
| `backtest/configs/` | Named YAML strategy configs (one file per named config) |
| `scripts/` | Operational scripts → [`CLAUDE.md`](scripts/CLAUDE.md) |
| `scripts/archive/` | Archived scripts — do not use as templates |
| `strategies/` | Strategy YAML configs (auto-loaded) → [`CLAUDE.md`](strategies/CLAUDE.md) |
| `tests/` | pytest suite → [`CLAUDE.md`](tests/CLAUDE.md) |

