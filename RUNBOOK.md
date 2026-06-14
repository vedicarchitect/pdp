# PDP Runbook

Operational reference for starting, running, and maintaining the PDP trading platform.

> **Safety first**: All commands default to **paper mode**. Live trading requires `LIVE=1` + `BROKER=dhan` + valid Dhan creds — see [Live Mode](#live-mode).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup](#2-first-time-setup)
3. [Starting the Stack](#3-starting-the-stack)
4. [Backend (API Server)](#4-backend-api-server)
5. [Frontend (UI)](#5-frontend-ui)
6. [Strategy Operations](#6-strategy-operations)
7. [Live Monitor](#7-live-monitor)
8. [Backtest](#8-backtest)
9. [Data Backfill](#9-data-backfill)
10. [Data Migration (Abi → MongoDB)](#10-data-migration-abi--mongodb)
11. [Paper Reset](#11-paper-reset)
12. [Live Mode](#12-live-mode)
13. [Database Admin](#13-database-admin)
14. [Health Checks](#14-health-checks)
15. [Common Troubleshooting](#15-common-troubleshooting)

---

## 1. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13 | `winget install Python.Python.3.13` |
| `uv` | latest | `pip install uv` |
| Node.js | ≥ 20 | `winget install OpenJS.NodeJS` |
| Docker Desktop | latest | [docker.com](https://www.docker.com/products/docker-desktop) |
| Perl | any | Pre-installed on WSL; or `winget install StrawberryPerl.StrawberryPerl` |
| Task | latest | `winget install Task.Task` |

---

## 2. First-Time Setup

```powershell
# 1. Clone and enter repo
cd c:\Users\prasa\OneDrive\Desktop\komalavalli\PDP

# 2. Install Python deps
uv sync

# 3. Copy and fill .env
cp .env.example .env
# Edit .env — minimum required:
#   DATABASE_URL, DATABASE_SYNC_URL, REDIS_URL are already correct for Docker defaults.
#   Add DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN only when you need live feed or backfill.

# 4. Start infrastructure
task db:up

# 5. Run DB migrations
task db:migrate

# 6. Install frontend deps
cd frontend && npm install && cd ..
```

---

## 3. Starting the Stack

### Minimum (paper trading, no live feed)

```powershell
task db:up        # starts postgres:5432 + redis:6379 + mongo:27017
task db:migrate   # apply any pending alembic migrations (safe to re-run)
task dev          # starts API on http://localhost:8000
```

### With live market feed (Dhan creds required in .env)

```powershell
# Same as above — the API auto-detects DHAN_CLIENT_ID and starts the feed
task dev
# Logs will show: market_feed_started client_id=...
```

### Full stack (API + Frontend)

```powershell
# Terminal 1
task db:up && task dev

# Terminal 2
cd frontend && npm run dev
# UI: http://localhost:5173
```

---

## 4. Backend (API Server)

### Start

```powershell
task dev
# Equivalent: uv run uvicorn pdp.main:app --reload --host 0.0.0.0 --port 8000
```

### What starts automatically on API startup

| Service | Condition |
|---------|-----------|
| PaperBroker | Always |
| StrategyHost | Always (loads `strategies/*.yaml`) |
| IndicatorEngine | Always |
| PortfolioService | Always |
| JournalService | Always |
| DhanTickerAdapter (market feed) | `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` set |
| DhanBroker (live orders) | `LIVE=1` + `BROKER=dhan` + creds set |
| OptionsChainPoller | `LIVE=1` + creds set |

### Key environment flags

| `.env` key | Effect |
|-----------|--------|
| `LIVE=false` | Paper mode (default) |
| `LIVE=true` + `BROKER=dhan` | Routes orders to Dhan |
| `DHAN_CLIENT_ID=<id>` | Enables market feed |
| `LOG_LEVEL=DEBUG` | Verbose structlog output |

### API endpoints (quick ref)

```
GET  /healthz                         → {status, git_sha, started_at}
GET  /readyz                          → {status, db, redis, mongo}
GET  /api/v1/orders                   → today's orders [?today=1]
GET  /api/v1/trades                   → today's trades
GET  /api/v1/portfolio/summary        → MTM P&L summary
GET  /api/v1/portfolio/positions      → open positions
GET  /api/v1/strategies               → loaded strategy configs + status
POST /api/v1/orders                   → place order
POST /risk/kill                       → manual kill-switch (flatten all)
GET  /api/v1/options/NIFTY/chain      → chain [?expiry=YYYY-MM-DD]
WS   /ws/market                       → tick stream
WS   /ws/orders                       → fill events
WS   /ws/portfolio                    → MTM P&L stream
WS   /ws/options                      → option chain updates
```

Interactive docs: `http://localhost:8000/docs`

---

## 5. Frontend (UI)

### Start dev server

```powershell
cd frontend
npm run dev
# → http://localhost:5173
```

### Build production bundle

```powershell
cd frontend
npm run build
# output: frontend/dist/
```

### Run frontend tests

```powershell
cd frontend
npm test
```

### Add a shadcn/ui component

```powershell
cd frontend
npx shadcn-ui@latest add <component-name>
# e.g. npx shadcn-ui@latest add table
```

---

## 6. Strategy Operations

### Current strategies

| File | ID | Description |
|------|----|-------------|
| `strategies/supertrend_short.yaml` | `supertrend_short` | ST(10,2)/15m NIFTY OTM-1 option selling. Paper-only. Promoted 2026-06-14. |

### Add a new strategy

1. Copy the template:
   ```powershell
   cp strategies\example.yaml.tpl strategies\my_strategy.yaml
   ```

2. Edit `strategies/my_strategy.yaml`:
   ```yaml
   id: my_strategy
   class: pdp.strategies.my_strategy.MyStrategy   # importable path
   watchlist:
     - security_id: "13"          # Dhan security ID (NIFTY index = 13)
       exchange_segment: IDX_I    # IDX_I / NSE_EQ / NSE_FNO
       timeframes: [5m]           # subset of: 1m 5m 15m 30m 1H
   params:
     otm_steps: 1
     lot_size: 65
     start_lots: 2
     max_lots: 5
     start_ist: "09:30"
     square_off_ist: "15:10"
     leg_stop_per_lot: 1000
     day_stop: 10000
   risk:
     max_open_orders: 12
     max_daily_loss_inr: 20000
   ```

3. Implement class at `src/pdp/strategies/my_strategy.py` (extends `pdp.strategy.abc.BaseStrategy`).

4. Restart API — `StrategyHost` auto-loads all `*.yaml`.

### Strategy YAML params reference

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `security_id` | str | — | Dhan security ID (NIFTY index = `"13"`) |
| `exchange_segment` | str | — | `IDX_I`, `NSE_EQ`, `NSE_FNO` |
| `timeframes` | list | — | `1m`, `5m`, `15m`, `30m`, `1H` |
| `otm_steps` | int | 1 | Strikes OTM (0=ATM, negative=ITM) |
| `strike_step` | int | 50 | NIFTY = 50, BANKNIFTY = 100 |
| `lot_size` | int | 65 | NIFTY = 65 |
| `start_lots` | int | 2 | Entry size on first signal |
| `add_lots` | int | 1 | Lots added per confirming bar |
| `max_lots` | int | 5 | Scale-in cap |
| `start_ist` | str | `"09:30"` | No entries before this (IST) |
| `square_off_ist` | str | `"15:10"` | Flatten all at/after this (IST) |
| `leg_stop_per_lot` | int | 1000 | Close leg if MTM loss ≥ N × lots |
| `day_stop` | int | 10000 | Halt if realized loss ≥ N |

---

## 7. Live Monitor

Perl-based read-only terminal monitor. Polls Redis + FastAPI every second. Shows NIFTY LTP, SuperTrend direction, open positions, per-leg P&L, Greeks, stop distance.

```powershell
task monitor
# Equivalent: perl scripts/monitor.pl

# Exit: Ctrl+C
```

Requirements:
- API running on `http://localhost:8000`
- Redis on `localhost:6379`
- Perl with modules: `LWP::UserAgent`, `JSON`, `IO::Socket::INET`, `Time::HiRes` (standard)

---

## 8. Backtest

### Main multi-day backtest runner

```powershell
# Run from repo root
task backtest
# Equivalent: uv run python backtest_multiday.py

# The script has flags at the top (module-level constants).
# Edit backtest_multiday.py directly to change:
#   START_DATE, DAYS, TF_MIN (timeframe), ST period/multiplier, OTM_STEPS
```

### Backtest compare (single day vs paper journal)

```powershell
# Default: today's IST date
uv run python scripts/backtest_compare.py

# Specific date
uv run python scripts/backtest_compare.py --date 2026-06-10

# Output: side-by-side backtest trades vs paper journal P&L for that day
```

### Backtest sweep (parameter grid)

```powershell
# Full grid (105 combos: 3 ST × 5 TF × 7 moneyness — ~2-3 min)
task backtest:sweep -- --days 90 --start 2026-06-12

# Narrow the grid (faster)
task backtest:sweep -- --st "10,2" --tf "5,15" --moneyness "1,0,-1" --days 90

# Winner vs baseline only
task backtest:sweep -- --st "3,1;10,2" --tf "5,15" --moneyness "1" --days 90

# Single config — prints full per-day/per-leg detail (verify a specific config)
task backtest:sweep -- --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":1}'

# Skip commissions (faster, logic testing only)
task backtest:sweep -- --days 90 --no-commission
```

Grid axes (defaults shown in `scripts/backtest_sweep.py` header):
- `--st` — `period,mult` pairs, semicolon-separated (default: `3,1;10,2;10,3`)
- `--tf` — timeframe minutes, comma-separated (default: `3,5,15,30,60`)
- `--moneyness` — `+N` OTM / `0` ATM / `−N` ITM (default: `3,2,1,0,-1,-2,-3`)

> **Data prerequisite**: Run spot + options backfill first (see §9) to avoid `[DATA INCOMPLETE]` days.

### Commission settings

Backtest commissions are configured in `.env` (nested under `BACKTEST_COMMISSION__`):

```bash
BACKTEST_COMMISSION__BROKERAGE_PER_ORDER=20.00
BACKTEST_COMMISSION__STT_RATE=0.001
BACKTEST_COMMISSION__TXN_CHARGE_RATE=0.0003553
BACKTEST_COMMISSION__SEBI_RATE=0.00001
BACKTEST_COMMISSION__STAMP_DUTY_RATE=0.00004
BACKTEST_COMMISSION__GST_RATE=0.18
```

---

## 9. Data Backfill

> **Requires** `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` in `.env`.
> Run spot backfill **before** options backfill (options derivation reads spot bars).

### Step 1 — NIFTY spot bars (1m, `market_bars`)

```powershell
# Dry-run — check planned days without fetching
uv run python scripts/backfill_nifty_spot.py --dry-run --from 2026-02-09 --to 2026-06-12

# Full backfill
uv run python scripts/backfill_nifty_spot.py --from 2026-02-09 --to 2026-06-12

# Only fill days below 95% bar coverage (faster, skips complete days)
uv run python scripts/backfill_nifty_spot.py --from 2026-02-09 --to 2026-06-12 --only-missing
```

**Args:**

| Flag | Default | Description |
|------|---------|-------------|
| `--from YYYY-MM-DD` | required | Start date |
| `--to YYYY-MM-DD` | today | End date (inclusive) |
| `--only-missing` | off | Skip days already at ≥ 95% of expected 375 bars |
| `--dry-run` | off | Report plan only; no Dhan calls or writes |

**Rate limit:** Dhan Data API = 5 req/s. Script auto-throttles. Backoff on DH-904.

### Step 2 — Options bars (1m, `option_bars`)

```powershell
# Dry-run
uv run python scripts/backfill_options_gap.py --dry-run

# Default window (ABI_CUTOFF_DATE → today)
uv run python scripts/backfill_options_gap.py

# Custom window
uv run python scripts/backfill_options_gap.py --from 2026-05-23 --to 2026-06-12

# Only missing days
uv run python scripts/backfill_options_gap.py --only-missing

# Wider strike band (default = WAREHOUSE_STRIKE_BAND=10, i.e. ATM±10 strikes)
uv run python scripts/backfill_options_gap.py --band 15

# Specific expiry codes (1=current week, 2=next week)
uv run python scripts/backfill_options_gap.py --codes 1,2
```

**Args:**

| Flag | Default | Description |
|------|---------|-------------|
| `--from YYYY-MM-DD` | `ABI_CUTOFF_DATE` from settings | Start date |
| `--to YYYY-MM-DD` | today | End date |
| `--codes 1,2` | `1,2` | Expiry codes (1=nearest weekly, 2=next) |
| `--band N` | `WAREHOUSE_STRIKE_BAND` (10) | ATM ± N strikes |
| `--only-missing` | off | Skip already-covered days |
| `--dry-run` | off | Report plan without fetching |

### Step 3 — Expired options (historical, one-time)

```powershell
uv run python scripts/backfill_expired_options.py --help
```

### Validate coverage after backfill

```powershell
# Audit option_bars coverage by date + strike
uv run python scripts/audit_options_coverage.py

# Validate warehouse integrity
uv run python scripts/validate_options_warehouse.py

# Verify NIFTY migration completeness
uv run python scripts/verify_nifty_migration.py
```

---

## 10. Data Migration (Abi → MongoDB)

Migrates historical NIFTY options OHLCV from the sibling Abi DuckDB project into MongoDB `option_bars`.

**Prerequisite:** Abi project checked out at `../Abi/` (sibling directory). Path configured via `ABI_NIFTY_DUCKDB` in `.env`.

```powershell
# Full historical migration
uv run python -m pdp.warehouse --from 2024-01-01 --to 2026-05-23

# Specific date range
uv run python -m pdp.warehouse --from 2025-01-01 --to 2025-12-31

# Dry-run (check Abi DB access)
uv run python -m pdp.warehouse --dry-run
```

The warehouse also runs **self-healing gap backfill** automatically while the API is running (`WAREHOUSE_GAP_BACKFILL_ENABLED=True`), scanning every `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS=4.0` hours.

---

## 11. Paper Reset

⚠️ **Destructive** — clears all paper orders, trades, and positions from PostgreSQL. Resets ID sequences to 1.

```powershell
task reset-paper
# Equivalent: uv run python scripts/reset_paper.py
```

Use before starting a fresh paper trading session. Does NOT touch MongoDB (market bars, option chains).

---

## 12. Live Mode

> **Paper-first is the default.** Enabling live trading requires explicit action.

### Enable live mode

In `.env`:

```bash
LIVE=true
BROKER=dhan
DHAN_CLIENT_ID=<your_client_id>
DHAN_ACCESS_TOKEN=<your_access_token>
```

Then start the API normally:

```powershell
task dev
# Log output: dhan_broker_enabled client_id=...
```

### Guards

- `LIVE=false` OR `BROKER=paper` → always routes to PaperBroker (no Dhan orders sent)
- `LIVE=true` + no `DHAN_CLIENT_ID` → still paper only (logs `dhan_broker_disabled`)
- Kill-switch fires automatically when `RISK_DAILY_LOSS_CAP_INR` is breached (default ₹50,000)
- Manual kill: `POST http://localhost:8000/risk/kill`

### Live-mode PowerShell launcher

```powershell
# Sets LIVE=1 and runs the CLI
.\pdp-live.ps1
```

---

## 13. Database Admin

### Migrations

```powershell
task db:migrate               # apply all pending migrations
uv run alembic upgrade head   # same thing
uv run alembic downgrade -1   # roll back one migration
uv run alembic current        # show current revision
uv run alembic history        # show migration history

# Create a new migration
uv run alembic revision --autogenerate -m "add my_table"
```

### pgAdmin (GUI)

```powershell
# Start pgAdmin (only when --profile tools)
docker compose --profile tools up -d pgadmin
# → http://localhost:5050  login: dev@pdp.local / pdp
```

### Direct DB access

```powershell
# PostgreSQL
docker exec -it pdp-postgres psql -U pdp -d pdp

# Redis
docker exec -it pdp-redis redis-cli
# Useful Redis commands:
#   KEYS ltp:*           -- all cached LTPs
#   GET ltp:13           -- NIFTY LTP
#   GET st:13:15m        -- SuperTrend state for NIFTY 15m (promoted config)
#   XLEN bars.13.5m      -- bar stream length

# MongoDB
docker exec -it pdp-mongo mongosh pdp
# Useful Mongo commands:
#   db.market_bars.countDocuments({})
#   db.option_bars.countDocuments({})
#   db.option_chains.countDocuments({})
#   db.paper_journal.find().sort({date:-1}).limit(5)
```

### Stop / restart infrastructure

```powershell
task db:down              # stop all containers (data persisted in volumes)
task db:up                # restart
docker compose down -v    # ⚠️ DESTROYS ALL DATA (drops volumes)
```

---

## 14. Health Checks

```powershell
# Quick liveness check
curl http://localhost:8000/healthz

# Full readiness (checks PG + Redis + Mongo)
curl http://localhost:8000/readyz

# Docker container status
docker compose ps

# API logs (follow)
task dev   # logs stream to terminal

# Check Redis LTP is being updated (NIFTY)
docker exec -it pdp-redis redis-cli GET ltp:13

# Check SuperTrend state (15m = promoted config)
docker exec -it pdp-redis redis-cli GET st:13:15m
```

---

## 15. Common Troubleshooting

### API won't start — DB connection error

```powershell
# Check containers are up
docker compose ps

# Check postgres is ready
docker exec pdp-postgres pg_isready -U pdp -d pdp

# Run migrations if missing tables
task db:migrate
```

### Market feed not starting

```
Log: market_feed_skipped reason="DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set"
```

→ Add `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` to `.env`.

### SuperTrend stuck / wrong direction after restart

The IndicatorEngine warms up from MongoDB `market_bars` on startup. If bars are missing:

```powershell
# Backfill NIFTY spot first
uv run python scripts/backfill_nifty_spot.py --from 2026-01-01 --only-missing
```

### Backtest shows [DATA INCOMPLETE] days

Missing spot bars for those dates. Run:

```powershell
uv run python scripts/backfill_nifty_spot.py --from 2026-02-09 --to 2026-06-12 --only-missing
```

Then re-run backtest. If options also missing:

```powershell
uv run python scripts/backfill_options_gap.py --only-missing
```

### Dhan rate limit (DH-904)

Scripts auto-backoff. If persistent, add a delay between runs or reduce `--band`.

### Reset stuck paper positions

```powershell
task reset-paper
```

### Run quality checks

```powershell
task lint       # ruff check + format --check
task fmt        # auto-fix formatting
task typecheck  # pyright strict
task test       # pytest
```

### Check OpenSpec status

```powershell
task openspec:list
# or
npx -y @fission-ai/openspec@latest list
```
