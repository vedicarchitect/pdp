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

## Key Commands

```bash
task dev          # uvicorn :8000 --reload
task db:up        # docker compose up postgres redis mongo
task db:migrate   # alembic upgrade head
task test         # pytest
task lint / fmt   # ruff
task typecheck    # pyright
task monitor      # perl scripts/monitor.pl (live Redis+API monitor)
task reset-paper  # scripts/reset_paper.py ⚠️ clears paper DB
task backtest     # uv run python backtest_multiday.py
task openspec:list
openspec validate --strict <id>
openspec archive <id>
```

## Module Index (read sub-folder CLAUDE.md for details)

| Path | Domain |
|------|--------|
| `src/pdp/main.py` | App factory + full lifespan wiring |
| `src/pdp/settings.py` | All env vars (pydantic-settings) |
| `src/pdp/market/` | Tick feed, bar agg, WS hub → [`CLAUDE.md`](src/pdp/market/CLAUDE.md) |
| `src/pdp/orders/` | Paper + Dhan broker, order router → [`CLAUDE.md`](src/pdp/orders/CLAUDE.md) |
| `src/pdp/strategy/` | Strategy host, registry, context → [`CLAUDE.md`](src/pdp/strategy/CLAUDE.md) |
| `src/pdp/indicators/` | IndicatorEngine, SuperTrend, warmup → [`CLAUDE.md`](src/pdp/indicators/CLAUDE.md) |
| `src/pdp/backtest/` | Backtest engine, sim, commissions → [`CLAUDE.md`](src/pdp/backtest/CLAUDE.md) |
| `src/pdp/portfolio/` | MTM P&L, kill-switch, fill events |
| `src/pdp/options/` | Chain poller (live-only), Greeks |
| `src/pdp/warehouse/` | Abi DuckDB → MongoDB pipeline |
| `frontend/` | Vite + React 19 + TanStack + shadcn → [`CLAUDE.md`](frontend/CLAUDE.md) |
| `scripts/` | Operational scripts — see [`scripts/README.md`](scripts/README.md) |
| `scripts/archive/` | One-time debug scripts (2026-06-08 session) — do not use as templates |
| `backtest_multiday.py` | **Main** multi-day backtest runner (58 KB) — active, do not move |
