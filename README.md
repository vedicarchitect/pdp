# PDP — OpenSpec-Driven Trading & Investment Platform

A self-hosted, **paper-first** trading and investment platform for intraday, positional, and portfolio management on Indian exchanges (NSE/BSE/MCX via Dhan). Every capability is spec-driven: no implementation without an OpenSpec proposal.

**Key Principles:**
- 📋 **Spec-first** — all features under `openspec/changes/<id>/` before coding
- 📄 **Paper-first** — `LIVE=1` + `BROKER=dhan` required for real orders
- ⚡ **Latency budget** — tick → WebSocket p99 ≤ 50ms
- 🗄️ **DB separation** — PostgreSQL (ACID ledger) · MongoDB (time-series) · Redis (hot cache)
- 🔍 **Structured logging** — JSON via structlog; no bare `print()` in core modules

---

## Quick Start

**Prerequisites:** Python 3.13 · `uv` · Docker Desktop · Node.js ≥ 20 · Task

```powershell
# 1. Install dependencies
uv sync

# 2. Copy env template (fill in DB/Redis/Mongo URLs — defaults work with Docker)
cp .env.example .env

# 3. Start infrastructure
task db:up          # postgres:5432  redis:6379  mongo:27017

# 4. Apply DB migrations
task db:migrate

# 5. Start API (http://localhost:8000)
task dev

# 6. (Optional) Start the Flutter app — offline mock data, no backend needed
cd app && flutter pub get && flutter run -d windows --dart-define=USE_MOCK=true
```

➡️ **Full operational details:** [RUNBOOK.md](RUNBOOK.md)

---

## All Tasks (`task --list`)

```
task dev                 Run API with hot reload (:8000)
task monitor             Live strategy monitor (Perl, Redis+API)
task reset-paper         ⚠️ Clear paper orders/trades/positions
task backtest            Run backtest_multiday.py

task test                pytest
task lint                ruff check + format --check
task fmt                 ruff format + fix
task typecheck           pyright

task db:up               Start postgres + redis + mongo
task db:down             Stop containers
task db:migrate          alembic upgrade head
task db:tools            Start pgAdmin (:5050)

task backfill:nifty      Backfill NIFTY 1m spot → market_bars
task backfill:banknifty  Backfill BANKNIFTY 1m spot → market_bars
task backfill:sensex     Backfill SENSEX 1m spot → market_bars
task backfill:options    Gap-fill option_bars from Dhan
task backfill:expired    Backfill expired-contract option bars

task audit:coverage      Audit option_bars coverage by date+strike
task validate:warehouse  Validate warehouse integrity
task validate:migration  Verify Abi → MongoDB migration

task backtest:compare    Backtest vs paper journal (single day)
task backtest:sweep      Multi-config parameter sweep

task openspec:list       List all changes
task openspec:show       Show a change
task openspec:validate   Validate a change
task openspec:archive    Archive a completed change
```

Pass args to parameterised tasks with `--`:
```powershell
task backfill:nifty -- --from 2026-02-09 --to 2026-06-12 --only-missing
task backtest:compare -- --date 2026-06-10
task openspec:validate -- configurable-strategy-backtest-sweep --strict
```

---

## Project Structure

```
PDP/
├── RUNBOOK.md                  # ← Full operational run guide (start here)
├── CLAUDE.md                   # Agent rules + module index
├── Taskfile.yml                # All task shortcuts
├── openspec/
│   ├── project.md              # Tech stack, architecture, conventions
│   ├── specs/                  # Archived capabilities (source of truth)
│   └── changes/                # In-flight proposals
├── src/pdp/
│   ├── main.py                 # FastAPI app factory + lifespan wiring
│   ├── settings.py             # All env vars (pydantic-settings)
│   ├── market/                 # Tick feed · BarAggregator · TickRouter · WSHub
│   ├── orders/                 # PaperBroker · DhanBroker · OrderRouter
│   ├── strategy/               # StrategyHost · BaseStrategy · StrategyContext
│   ├── indicators/             # IndicatorEngine · SuperTrend · warmup
│   ├── backtest/               # BacktestEngine · sim · commissions · output
│   ├── options/                # OptionsChainPoller · Greeks · gap_backfill
│   ├── warehouse/              # Options warehouse — Dhan gap-backfill loop
│   ├── portfolio/              # PortfolioService · MTM P&L · kill-switch
│   ├── journal/                # JournalService · fill recording · daily stats
│   ├── risk/                   # KillSwitchService · hard-cap auto-kill
│   ├── alerts/                 # AlertEvaluator · AlertsHub
│   ├── positional/             # Swing F&O + equity positions
│   ├── instruments/            # Dhan scrip master
│   ├── mongo/                  # MongoDB client + collection init
│   └── db/                     # SQLAlchemy session + base
├── app/                        # Flutter (Dart) trading app — Riverpod + fl_chart (Android + Windows)
├── strategies/                 # Strategy YAML configs (auto-loaded)
│   └── supertrend_short.yaml   # Active: ST(3,1) NIFTY OTM selling
├── scripts/                    # Operational scripts (see scripts/README.md)
│   ├── backfill_spot.py
│   ├── backfill_options_gap.py
│   ├── backtest_compare.py
│   ├── backtest_sweep.py
│   ├── audit_options_coverage.py
│   ├── validate_options_warehouse.py
│   ├── monitor.pl
│   ├── reset_paper.py
│   └── archive/                # One-time debug scripts (do not use as templates)
├── backtest_multiday.py        # Main multi-day backtest runner (58 KB)
├── tests/                      # pytest suite
├── alembic/                    # DB migrations
└── docker-compose.yml          # postgres · redis · mongo · pgadmin (profile:tools)
```

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Runtime | Python 3.13 · `uv` |
| API | FastAPI + uvicorn (uvloop / httptools) |
| Response models | `msgspec.Struct` (hot path) · `pydantic` (input) |
| DataFrame | Polars |
| PG ORM | SQLAlchemy 2.0 async + Alembic |
| HTTP client | httpx async |
| Logs | structlog JSON |
| Lint / types | ruff · pyright (strict on `src/pdp/`) |
| Task runner | Taskfile |
| Broker | Dhan (paper + live-gated) |
| App (UI) | Flutter (Dart) + Riverpod + fl_chart + web_socket_channel (Android + Windows) |

---

## OpenSpec Workflow

```powershell
# List in-flight proposals
task openspec:list

# Start a new feature
npx -y @fission-ai/openspec@latest new my-feature

# Validate before coding
task openspec:validate -- my-feature --strict

# After implementation: promote to specs/
task openspec:archive -- my-feature
```

See [openspec/project.md](openspec/project.md) for full architecture and conventions.

---

## Data Backfill (Dhan creds required)

```powershell
# Spot bars first (options depend on spot for strike derivation)
task backfill:nifty -- --from 2026-02-09 --to 2026-06-12 --only-missing

# Options bars (post Abi cutoff)
task backfill:options -- --only-missing

# Validate coverage
task audit:coverage
task validate:warehouse
```

---

## Live Trading

Default is **always paper**. To enable real orders:

```bash
# .env
LIVE=true
BROKER=dhan
DHAN_CLIENT_ID=<id>
DHAN_ACCESS_TOKEN=<token>
```

Risk guards active in all modes:
- `RISK_DAILY_LOSS_CAP_INR=50000` → auto kill-switch
- `POST /risk/kill` → manual flatten

---

## Capability Status

| Capability | Status | Notes |
|------------|--------|-------|
| Platform core + DB setup | ✅ Live | FastAPI + PG + Redis + Mongo |
| Instrument registry | ✅ Live | Dhan scrip master sync |
| Market data feed | ✅ Live | Dhan WS → TickRouter → bars |
| Paper broker | ✅ Live | Redis LTP fill + slippage |
| Dhan live broker | ✅ Live | Live-gated (`LIVE=1`) |
| Order routing | ✅ Live | Paper ↔ live switch |
| Strategy host | ✅ Live | YAML configs, auto-load |
| Indicator engine | ✅ Live | SuperTrend(3,1) universal |
| Portfolio MTM | ✅ Live | Real-time P&L + kill-switch |
| Paper journal | ✅ Live | Fill recording + daily stats |
| Backtest engine | ✅ Live | Multi-day, commissions |
| Options warehouse | ✅ Live | MongoDB + Dhan gap-backfill |
| Options gap backfill | ✅ Live | Self-healing loop + script |
| Options chain poller | ✅ Live | Live-only, Greeks |
| Alerts engine | ✅ Live | Price/Greeks alerts + WS |
| Positional monitor | ✅ Live | Swing F&O + equity |
| App (Flutter) | 🔄 In progress | `replace-frontend-flutter` — shell + live portfolio |
| Backtest sweep | 🔄 In progress | `configurable-strategy-backtest-sweep` |
| Order approval center | 🔄 In progress | Manual gate before live |

---

## Resources

- 📖 **Runbook** (how to run everything): [RUNBOOK.md](RUNBOOK.md)
- 🏗️ **Architecture & Tech Stack**: [openspec/project.md](openspec/project.md)
- 🤖 **Agent Guidance**: [CLAUDE.md](CLAUDE.md)
- 📜 **Scripts Reference**: [scripts/README.md](scripts/README.md)
- 📚 **API Docs**: http://localhost:8000/docs (when running)
- 🌐 **Dhan SDK**: [dhanhq on PyPI](https://pypi.org/project/dhanhq/)
