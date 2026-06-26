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
16. [Alert System — Setup & Usage Guide](#16-alert-system--setup--usage-guide)

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
npm test                     # vitest unit tests
npx playwright test          # e2e suite (required after every frontend change)
npx playwright test --grep "Positional route"  # run a single describe block
```

### Frontend routes

| Route | Description |
|-------|-------------|
| `/` | Intraday dashboard — positions, risk banner, alert pills, WS feeds |
| `/positional` | Swing/F&O positional view — strategy groups, per-leg Greeks, DTE alerts, P&L history |
| `/analytics` | Options analytics — GEX, Max Pain, OI Heatmap/PCR (nearest expiry by default) |
| `/portfolio` | MTM P&L overview + kill-switch |
| `/instruments` | Instrument browser + option chain viewer |
| `/backtest` | Backtest runner UI |
| `/builder` | Strategy payoff builder with 10 readymades |
| `/strategies` | Strategy manager |
| `/events` | Live event feed |
| `/operations` | Housekeeping / ML job runner |
| `/alerts` | Alert rule CRUD |

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

All backtest tooling lives in `backtest/`. Entry point: `backtest/run.py`.
Named configs live in `backtest/configs/*.yaml`. See [`backtest/CLAUDE.md`](backtest/CLAUDE.md).

### Per-trade detail (default config)

```powershell
# Last 7 days for the active config (BACKTEST_DEFAULT_CONFIG env var)
task backtest

# Named config, custom window
task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30

# Inline JSON config
task backtest -- --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":1}'
```

### Parameter grid sweep

```powershell
# Pass at least one grid flag (--st / --tf / --moneyness) to trigger grid mode

# Winner vs baseline, 90 days
task backtest:sweep -- --days 90 --st "3,1;10,2" --tf "5,15" --moneyness "1"

# Full grid (105 combos: 3 ST × 5 TF × 7 moneyness — ~2-3 min)
task backtest:sweep -- --days 90 --st "3,1;10,2;10,3" --tf "3,5,15,30,60" --moneyness "3,2,1,0,-1,-2,-3"

# Skip commissions (faster, logic testing only)
task backtest:sweep -- --days 90 --st "10,2" --no-commission
```

Grid axes (`backtest/run.py` defaults when axis is omitted):
- `--st` — `period,mult` pairs, semicolon-separated (default: `3,1;10,2;10,3`)
- `--tf` — timeframe minutes, comma-separated (default: `3,5,15,30,60`)
- `--moneyness` — `+N` OTM / `0` ATM / `−N` ITM (default: `3,2,1,0,-1,-2,-3`)

### Backtest compare (single day vs paper journal)

```powershell
# Default: today's IST date
task backtest:compare

# Specific date
task backtest:compare -- --date 2026-06-10
```

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
uv run python scripts/backfill_spot.py --dry-run --from 2026-02-09 --to 2026-06-12

# Full backfill
uv run python scripts/backfill_spot.py --from 2026-02-09 --to 2026-06-12

# Only fill days below 95% bar coverage (faster, skips complete days)
uv run python scripts/backfill_spot.py --from 2026-02-09 --to 2026-06-12 --only-missing
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
# Backfill spot first
uv run python scripts/backfill_spot.py --from 2026-01-01 --only-missing
```

### Backtest shows [DATA INCOMPLETE] days

Missing spot bars for those dates. Run:

```powershell
uv run python scripts/backfill_spot.py --from 2026-02-09 --to 2026-06-12 --only-missing
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

---

## 16. Alert System — Setup & Usage Guide

This section documents every market event type you want monitored, with exact steps for
setting up each one today, plus clear status when an event type requires a future OpenSpec
change.

### Status legend

| Icon | Meaning |
|------|---------|
| ✅ | Works today via the alerts API |
| 🔧 | Infrastructure exists (indicator computed); alert condition type not yet wired |
| 🚧 | Needs new OpenSpec change to implement |

### How the alert system works

Alerts are stored in PostgreSQL, evaluated on every tick (price/Greeks) or bar close
(indicator-based), and pushed to the UI over WebSocket (`WS /ws/alerts`).

**Alert lifecycle:** `ARMED` → `TRIGGERED` → `RESOLVED` (auto-resolves when condition clears).

---

### 16.1 Price Near Indicator Level (FVG / Fibonacci / EMA) ✅ / 🔧

Use case: "Alert when NIFTY is near the 1h 50-EMA, near an FVG gap, or near a Fibonacci
retracement level."

**What works today (plain price threshold):**

```powershell
# Alert when NIFTY crosses 23600
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "security_id": "13",
    "condition": "PRICE_LT",
    "threshold": 23600
  }'
```

Create one alert with `PRICE_GT` for the upper band and one with `PRICE_LT` for the
lower band to define a proximity zone.

**To get the live indicator levels:**

```powershell
# Read EMA50 for the 1h timeframe from Redis
docker exec -it pdp-redis redis-cli GET "suite:13:1H"

# Or via the API
curl http://localhost:8000/api/v1/market/indicators?security_id=13&timeframe=1H
```

Use the returned EMA50 value as your `threshold` in the price alert.

**Indicator suite already computes (🔧 — not yet alert-wired):**

| Indicator | What's available | Where |
|-----------|-----------------|-------|
| EMA (9/20/50/100/200) | All periods, all timeframes | `IndicatorEngine.get_ema()` |
| Fair Value Gaps | Unfilled gap list, nearest gap bounds | `IndicatorEngine.get_fvg()` |
| Fibonacci levels | Nearest retracement/extension + distance | `IndicatorEngine.get_fib_levels()` |
| Elliott Wave | Current wave label + position + confidence | `IndicatorEngine.get_elliott()` |

Full `PRICE_NEAR_LEVEL` alert condition (auto-read indicator level, configurable tolerance)
requires an OpenSpec change to `alerts/`.

---

### 16.2 OI Wall Resistance / Rejection 🚧

Use case: "Alert when NIFTY approaches or rejects from a strong OI wall (e.g. 24000 CE)."

**What works today (proxy — price threshold):**

```powershell
# Arm a price alert at the OI wall strike
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": 24000}'
```

**Read current OI walls manually:**

```powershell
# Options analytics endpoint (if live + credentialed)
curl "http://localhost:8000/api/v1/options/NIFTY/analytics"
# Returns: max_pain, pcr, gex, oi_wall_above, oi_wall_below
```

**What's needed (🚧):** A new alert condition type `OI_WALL_NEAR` that reads
`oi_wall_above` / `oi_wall_below` from the options analytics and fires when NIFTY is
within a configurable distance.

---

### 16.3 EMA Crossover Alert 🔧

Use case: "Alert when 9-EMA crosses above 20-EMA or 50-EMA on 5m/15m/30m/60m/Daily."

**What works today (manual check via Redis):**

```powershell
# Check current EMA snapshot for 15m
docker exec -it pdp-redis redis-cli GET "suite:13:15m"
# Returns JSON blob with ema_9, ema_20, ema_50 — compare manually
```

**Arm price alerts near expected crossover zones:**

```powershell
# Example: alert when 15m NIFTY closes above 50-EMA (read current EMA first, then set)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": <ema50_value>}'
```

**What's needed (🔧):** New `EMA_CROSS_ABOVE` / `EMA_CROSS_BELOW` condition types in
`alerts/enums.py` + evaluator logic calling `IndicatorEngine.get_ema()` on each bar close.

**Timeframes to cover:** 5m, 15m, 30m, 1H, 1D.

---

### 16.4 Volume / Trend Change Analysis 🔧

Use case: "Alert on unusually high volume that signals a trend change or confirms support/resistance."

**What works today (manual check):**

```powershell
# VWMA snapshot for 15m (volume-weighted moving average)
docker exec -it pdp-redis redis-cli GET "suite:13:15m"
# Contains vwma_20 field

# Or query market_bars for volume
docker exec -it pdp-mongo mongosh pdp --eval \
  "db.market_bars.find({security_id:'13',timeframe:'15m'}).sort({ts:-1}).limit(5)"
```

**What's needed (🔧):** New `VOLUME_SPIKE` condition type — fires when current bar
volume exceeds N × rolling-average volume (e.g. `volume > 2.5 × vwma_20`). Needs
a `VolumeTracker` or leverage existing VWMA state.

---

### 16.5 Strangle Range Break Alert ✅

Use case: "Alert when NIFTY breaks the range defined by your active strangle strikes."

**Step 1 — Find your current strangle strikes:**

```powershell
curl http://localhost:8000/api/v1/portfolio/positions
# Note the CE strike (upper bound) and PE strike (lower bound)
```

**Step 2 — Arm two price alerts:**

```powershell
# Upper bound (CE strike) — fires if underlying approaches ITM
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": <ce_strike>}'

# Lower bound (PE strike)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_LT", "threshold": <pe_strike>}'
```

**Step 3 — Arm P&L alerts as backup:**

```powershell
# Alert when daily P&L loss exceeds ₹8,000
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PNL_LT", "threshold": -8000}'
```

**Re-arm after adjusting strikes:** List alerts, delete stale ones, post new thresholds.

```powershell
curl http://localhost:8000/api/v1/alerts               # list
curl -X DELETE http://localhost:8000/api/v1/alerts/<id> # delete
```

---

### 16.6 Directional Trade — Critical Junction Alert 🔧

Use case: "Alert when the directional trade is at a confluence of SuperTrend + EMA + Pivot support/resistance."

**Available today — composite manual check:**

```powershell
# SuperTrend state for NIFTY 15m
docker exec -it pdp-redis redis-cli GET "st:13:15m"
# {"direction":"up","upper":23450.5,"lower":22100.2,"close":23600.0}

# Indicator suite snapshot (all families)
docker exec -it pdp-redis redis-cli GET "suite:13:15m"
# Contains ema_9, ema_20, pivot_pp, pivot_s1, pivot_r1, ...
```

**Proxy alert (price at pivot/ST level):**

```powershell
# Alert when price crosses the SuperTrend line (read value first, then set)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_LT", "threshold": <st_lower_band>}'
```

**What's needed (🔧):** Composite `LEVEL_CONFLUENCE` condition that fires when price
is within tolerance of ≥ 2 of: ST band, EMA, pivot level, Fibonacci level.

---

### 16.7 OI Trend Change Detection 🚧

Use case: "Alert when OI buildup or unwinding signals a trend shift (e.g. CE OI rising while PE OI falling = bearish)."

**What works today (manual query):**

```powershell
# Check OI data for the active expiry
curl "http://localhost:8000/api/v1/options/NIFTY/chain"
# Inspect oi_change on CE vs PE for each strike
```

**Useful Redis check:**

```powershell
# Options hub publishes latest chain to WS; connect and observe
# ws://localhost:8000/ws/options
```

**What's needed (🚧):** A new `OI_TREND_CHANGE` condition in the options analytics
pipeline that detects PCR crossing a threshold or directional OI accumulation pattern.

---

### 16.8 Delta-Neutral Portfolio Tracking ✅ / 🚧

Use case: "Monitor aggregate portfolio delta across all option legs; alert when delta deviates beyond tolerance."

**What works today (read aggregate delta):**

```powershell
# Portfolio summary — includes MTM and Greek roll-up
curl http://localhost:8000/api/v1/portfolio/summary

# Open positions with per-leg Greeks
curl http://localhost:8000/api/v1/portfolio/positions
```

**Arm a delta alert on a specific leg:**

```powershell
# Alert when leg delta exceeds 0.50 (approaching ATM)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "<option_security_id>", "condition": "DELTA_GT", "threshold": 0.50}'
```

**What's needed (🚧):** A portfolio-level `NET_DELTA_GT` / `NET_DELTA_LT` condition
that aggregates delta across all open positions and fires when the net exceeds a signed
threshold. Requires extending `AlertEvaluator.evaluate_greeks()` to receive a
portfolio-rolled-up delta.

---

### 16.9 SuperTrend Break — Multiple Timeframes 🔧

Use case: "Alert when SuperTrend(10,2) flips direction in any of 5m/15m/30m/1H."

**What works today (manual Redis poll):**

```powershell
# Check all timeframes
foreach ($tf in @("5m","15m","30m","1H")) {
  docker exec -it pdp-redis redis-cli GET "st:13:$tf"
}
```

**Proxy alert (price crosses ST band):**

```powershell
# Read the current ST lower band for 15m, then arm price alert
$st = docker exec -it pdp-redis redis-cli GET "st:13:15m" | ConvertFrom-Json
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d "{\"security_id\": \"13\", \"condition\": \"PRICE_LT\", \"threshold\": $($st.lower)}"
```

**What's needed (🔧):** New `SUPERTREND_FLIP` condition type evaluated on each
`on_bar` — reads the new ST direction from `IndicatorEngine.get()`, compares to
previous tick's direction, fires on flip. Must run for every configured timeframe
independently.

---

### 16.10 Sudden Volume / OI Spike 🚧

Use case: "Alert when futures volume or OI makes an unusual spike (≥ 2× rolling average)."

**What works today (manual query):**

```powershell
# Last 10 bars with volume for NIFTY futures
docker exec -it pdp-mongo mongosh pdp --eval \
  "db.market_bars.find({security_id:'13',timeframe:'5m'},{ts:1,volume:1,_id:0}).sort({ts:-1}).limit(10)"

# OI snapshot from latest chain
curl "http://localhost:8000/api/v1/options/NIFTY/analytics"
```

**What's needed (🚧):** Rolling-window volume tracker (ratio of current bar volume to
N-bar average) + new `VOLUME_SPIKE` alert condition. OI spike requires the same
pattern applied to OI change series.

---

### 16.11 PDH / PDL / PWH / PWL / PMH / PML Break Alert ✅ / 🔧

Use case: "Alert when NIFTY breaks prior day high/low, prior week high/low, or prior month high/low."

**Prior Day High/Low — works today via price alert:**

```powershell
# Step 1: Get yesterday's high/low from market_bars
docker exec -it pdp-mongo mongosh pdp --eval "
  db.market_bars.aggregate([
    {\$match: {security_id:'13', timeframe:'1D'}},
    {\$sort: {ts:-1}},
    {\$limit: 2},
    {\$group: {_id:null, pdh:{\$max:'\$high'}, pdl:{\$min:'\$low'}}}
  ])"
# Returns {pdh: 24150.5, pdl: 23410.2}

# Step 2: Arm alerts
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": 24150.5}'  # PDH break

curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_LT", "threshold": 23410.2}'  # PDL break
```

**Prior Week / Month High/Low — same pattern, wider query:**

```powershell
# Prior week high (last 5 trading days)
docker exec -it pdp-mongo mongosh pdp --eval "
  db.market_bars.aggregate([
    {\$match: {security_id:'13', timeframe:'1D'}},
    {\$sort: {ts:-1}},
    {\$limit: 6},
    {\$skip: 1},
    {\$group: {_id:null, pwh:{\$max:'\$high'}, pwl:{\$min:'\$low'}}}
  ])"
```

**What's needed (🔧):** Auto-updating `SESSION_BREAK` condition type that refreshes
the PDH/PDL/PWH/PWL values at session open rather than requiring manual re-arm each day.
The PivotTracker already computes prior-session levels for standard pivots.

---

### 16.12 Gap-Up / Gap-Down Impact Alert 🔧

Use case: "Alert on gap-up or gap-down at market open and assess impact on active strategies."

**Check today's gap manually (after 09:15 IST):**

```powershell
# First bar of today vs yesterday's close
docker exec -it pdp-mongo mongosh pdp --eval "
  var bars = db.market_bars.find({security_id:'13',timeframe:'1D'}).sort({ts:-1}).limit(2).toArray();
  var gap_pct = ((bars[0].open - bars[1].close) / bars[1].close * 100).toFixed(2);
  print('Gap: ' + gap_pct + '%');"
```

**Arm a gap alert preemptively (arm before market open):**

```powershell
# If yesterday's close was 23800, a 0.5% gap-up would be at 23919
# Arm a high-open alert
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": 23919}'
```

**What's needed (🔧):** `GAP_UP` / `GAP_DOWN` condition type that fires on the first
bar of the session if `open - prev_close` exceeds a configurable %. Needs access to
prior-session close (already in `PivotTracker`).

---

### 16.13 Trades, Positions & Portfolio Sync ✅

All trade/position/portfolio data is available today via REST and WebSocket.

**Key endpoints:**

```powershell
# Live MTM P&L summary
curl http://localhost:8000/api/v1/portfolio/summary

# All open positions with Greeks
curl http://localhost:8000/api/v1/portfolio/positions

# Today's orders
curl "http://localhost:8000/api/v1/orders?today=1"

# Today's fills
curl http://localhost:8000/api/v1/trades

# Daily journal stats (paper_journal in Mongo)
curl http://localhost:8000/api/v1/journal/stats

# Subscribe to live P&L stream (WebSocket)
# ws://localhost:8000/ws/portfolio
# ws://localhost:8000/ws/orders
```

**Live monitor (terminal):**

```powershell
task monitor
# Shows: NIFTY LTP, ST direction, open positions, per-leg P&L, Greeks, stop distance
```

---

### 16.14 Trade Count / Premium / P&L / MaxLoss / MaxProfit Alerts ✅ / 🔧

**What works today:**

```powershell
# Arm a P&L alert (fires when daily realized loss breaches ₹10,000)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PNL_LT", "threshold": -10000}'

# Arm a P&L alert for profit target (fires when P&L exceeds ₹15,000)
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PNL_GT", "threshold": 15000}'

# Check current stats
curl http://localhost:8000/api/v1/journal/stats
# Returns: trade_count, total_premium_received, realized_pnl, max_loss, max_profit
```

**The kill-switch fires automatically when `RISK_DAILY_LOSS_CAP_INR` is breached:**

```bash
# .env
RISK_DAILY_LOSS_CAP_INR=50000   # hard cap — flattens all positions automatically
```

**What's needed (🔧):** Dedicated `TRADE_COUNT_GT` and `PREMIUM_RECEIVED_GT` condition
types so you can alert on "more than 6 trades placed today" or "total premium > ₹X"
directly, without reading journal stats manually.

---

### 16.15 Managing Alerts (CRUD reference)

```powershell
# List all active alerts
curl http://localhost:8000/api/v1/alerts

# Create an alert
curl -X POST http://localhost:8000/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '{"security_id": "13", "condition": "PRICE_GT", "threshold": 24000}'

# Delete an alert
curl -X DELETE http://localhost:8000/api/v1/alerts/<id>

# Alert conditions available today
# PRICE_GT / PRICE_LT    → underlying price
# DELTA_GT / DELTA_LT    → option delta
# GAMMA_GT / GAMMA_LT    → option gamma
# VEGA_GT  / VEGA_LT     → option vega
# PNL_GT   / PNL_LT      → position P&L

# Subscribe to alerts over WebSocket
# ws://localhost:8000/ws/alerts
```

---

### 16.16 Alert Roadmap Summary

The following new condition types need OpenSpec changes to implement fully:

| Condition type | Event | Infrastructure ready |
|---|---|---|
| `EMA_CROSS_ABOVE` / `EMA_CROSS_BELOW` | EMA crossover any TF | ✅ EMA in suite |
| `SUPERTREND_FLIP` | ST direction change any TF | ✅ ST in engine |
| `PRICE_NEAR_LEVEL` | Near FVG / Fibonacci / EMA (tolerance) | ✅ All in suite |
| `SESSION_BREAK` | PDH/PDL/PWH/PWL/PMH/PML auto-refresh | 🔧 Pivot tracker |
| `VOLUME_SPIKE` | Volume > N × rolling avg | 🔧 VWMA in suite |
| `GAP_UP` / `GAP_DOWN` | Open vs prev-close gap % | 🔧 Pivot tracker |
| `OI_WALL_NEAR` | Price near OI wall strike | ✅ Options analytics |
| `OI_TREND_CHANGE` | PCR / OI accumulation flip | ✅ Options analytics |
| `NET_DELTA_GT/LT` | Portfolio aggregate delta | ✅ Greeks in positions |
| `TRADE_COUNT_GT` | More than N trades today | ✅ Journal stats |
| `PREMIUM_RECEIVED_GT` | Total premium > ₹X | ✅ Journal stats |
