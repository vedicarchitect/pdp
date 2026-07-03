# PDP Runbook

Operational reference for starting, running, and maintaining the PDP trading platform.

> **Safety first**: All commands default to **paper mode**. Live trading requires `LIVE=1` + `BROKER=dhan` + valid Dhan creds — see [Live Mode](#live-mode).

> **Working directory (since the repo restructure)**: all Python lives in `backend/`. Bare
> `uv run …`, `cp .env.example .env`, and `scripts/…` / `backtest/…` commands below are run
> **from `backend/`** (`.env` lives there too). The root `task` shortcuts work from the repo
> root regardless — they `cd` into `backend/` (or `infra/compose/`) for you. `cd app …`
> commands run from the repo root.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup](#2-first-time-setup)
3. [Starting the Stack](#3-starting-the-stack)
4. [Backend (API Server)](#4-backend-api-server)
5. [App (Flutter UI)](#5-app-flutter-ui)
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
17. [Directional Strangle — Paper Mode Operations](#17-directional-strangle--paper-mode-operations)
18. [Unified Log Pipeline (OpenSearch)](#18-unified-log-pipeline-opensearch)
19. [Strangle Live-Paper Hardening](#19-strangle-live-paper-hardening-change-strangle-live-paper-hardening)

---

## 1. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13 | `winget install Python.Python.3.13` |
| `uv` | latest | `pip install uv` |
| Node.js | ≥ 20 | `winget install OpenJS.NodeJS` |
| Docker Desktop | latest | [docker.com](https://www.docker.com/products/docker-desktop) |
| Flutter | ≥ 3.22 | Extract to `C:\src\flutter`; add `C:\src\flutter\bin` to User PATH. **Windows desktop builds require Developer Mode** (`start ms-settings:developers`). If conda is in PATH, add the registry-refresh line to `$PROFILE` so Flutter survives new shells: `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')` |
| Perl | any | Pre-installed on WSL; or `winget install StrawberryPerl.StrawberryPerl` |
| Task | latest | `winget install Task.Task` |

---

## 2. First-Time Setup

```powershell
# 1. Clone and enter the backend (all Python lives here)
cd c:\Users\prasa\OneDrive\Desktop\komalavalli\PDP\backend

# 2. Install Python deps (dev extra adds ruff/pytest/pyright)
uv sync --extra dev

# 3. Copy and fill .env (stays in backend/)
cp .env.example .env
# Edit .env — minimum required:
#   DATABASE_URL, DATABASE_SYNC_URL, REDIS_URL are already correct for Docker defaults.
#   Add DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN only when you need live feed or backfill.

# 4. Start infrastructure
task db:up

# 5. Run DB migrations
task db:migrate

# 6. Install app (Flutter) deps — requires the Flutter SDK on PATH
cd app && flutter pub get && cd ..
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

### Full stack (API + App)

```powershell
# Terminal 1
task db:up && task dev

# Terminal 2 — Windows desktop, live against the local API
cd app
flutter run -d windows --dart-define=API_BASE=http://localhost:8000 --dart-define=WS_BASE=ws://localhost:8000
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
| OptionsChainPoller | `OPTIONS_POLLER_ENABLED=true` (default) + creds set — paper-safe, no `LIVE=1` needed |

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

## 5. App (Flutter UI)

The UI is a native **Flutter** app in `app/` (Dart, Riverpod, fl_chart, web_socket_channel),
targeting **Android** and **Windows desktop**. Requires the [Flutter SDK](https://docs.flutter.dev/get-started/install)
on PATH (`flutter --version`). First run on a fresh clone:

```powershell
cd app
flutter create . --platforms=android,windows   # generates android/ + windows/ host folders (one-time)
flutter pub get
```

### Run

```powershell
cd app

# Offline demo — simulated live data, no backend needed
flutter run -d windows --dart-define=USE_MOCK=true

# Live against the local API (start it with `task dev` first)
flutter run -d windows --dart-define=API_BASE=http://localhost:8000 --dart-define=WS_BASE=ws://localhost:8000

# Android device on the same LAN — point at the host machine's IP
flutter run -d <device-id> --dart-define=API_BASE=http://<host-ip>:8000 --dart-define=WS_BASE=ws://<host-ip>:8000
```

`flutter devices` lists attached targets. Defaults (no dart-defines) are
`http://localhost:8000` / `ws://localhost:8000`, mock off.

### Build

```powershell
cd app
flutter build windows        # → build/windows/x64/runner/Release/
flutter build apk            # → build/app/outputs/flutter-apk/app-release.apk
```

### Test & lint

```powershell
cd app
flutter analyze              # static analysis — must be clean
flutter test                 # widget/unit tests
```

### Backend connection (`--dart-define`)

| Define | Default | Purpose |
|--------|---------|---------|
| `API_BASE` | `http://localhost:8000` | REST base (`/api/v1/...`) |
| `WS_BASE` | `ws://localhost:8000` | WebSocket base (`/ws/...`) |
| `USE_MOCK` | `false` | Simulated live data, zero backend |

### Screens

| Screen | Description |
|--------|-------------|
| Portfolio | Live MTM P&L summary + positions list + P&L chart (REST snapshot + `/ws/portfolio`) |

> The first build ships the app shell + the Portfolio vertical slice. Further screens
> (orders, analytics, backtest console, events, alerts) land as separate OpenSpec changes,
> each reusing the shell + data/provider pattern.

---

## 6. Strategy Operations

### Current strategies

| File | ID | Description |
|------|----|-------------|
| `strategies/supertrend_short.yaml` | `supertrend_short` | ST(10,2)/15m NIFTY OTM-1 option selling. Paper-only. Promoted 2026-06-14. |
| `strategies/directional_strangle.yaml` | `directional_strangle` | Bias-driven multi-TF NIFTY ratio strangle. Paper-only. 5yr backtest: Rs 85.6L / PF 5.72. See §17. |

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

3. Implement class at `backend/pdp/strategies/my_strategy.py` (extends `pdp.strategy.abc.BaseStrategy`).

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

# Default window (from earliest available data → today)
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
| `--from YYYY-MM-DD` | earliest available data | Start date |
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

```

---

## 10. Options Warehouse Gap Backfill

The warehouse runs **self-healing gap backfill** automatically while the API is running (`WAREHOUSE_GAP_BACKFILL_ENABLED=True`), scanning every `WAREHOUSE_GAP_CHECK_INTERVAL_HOURS=4.0` hours.

To manually trigger a gap fill for a specific range:

```powershell
# Gap-fill options from Dhan API
task backfill:options -- --from 2026-06-01 --to 2026-06-25 --only-missing
```

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

---

## 17. Directional Strangle — Paper Mode Operations

Bias-driven NIFTY ratio strangle. Sells PE:CE lots proportional to multi-TF signal strength.
5-year backtest (Sep 2021–Jun 2026): **+Rs 85.6L | PF 5.72 | MaxDD Rs 71k | Win 75%**.
All years profitable. Zero losing months. See `strategies/MultiTimeFrameSelling.txt` for full reference.

### 17.1 Pre-market setup (before 09:00 IST)

```powershell
task db:up        # ensure postgres:5432 + redis:6379 + mongo:27017 are running
task db:migrate   # apply any pending migrations (safe to re-run)
task dev          # start API on http://localhost:8000 (paper mode by default)
```

Verify the strategy loaded:
```powershell
curl http://localhost:8000/api/v1/strategies
# Look for: {"id": "directional_strangle", "status": "active"}
```

### 17.2 What happens at 10:15

The strategy waits silently until 10:15 IST (after the first 1h candle closes and the 15m ORB is set). At 10:15 the following happens on every 5m bar:

1. `bias_evaluated` — structlog line with score, bucket, gated flag, short count
2. If not gated: open PE and CE shorts per bucket ratio (×scale_lots=2)
3. `short_opened` — leg confirmation with strike, lots, security_id
4. `hedge_opened` — far-OTM protective wing (Rs 2–5 premium) bought per short leg
5. On every subsequent 5m bar: check exits (TP 50%, stop 30/40%, rollup, flip, day_loss)
6. `all_legs_closed square_off` — automatic close at 15:10 IST

### 17.3 Key log events to monitor

```
directional_strangle_init  — startup, confirms params
bias_evaluated             — every 5m: score, bucket, gated=true/false
short_opened               — leg entry: opt_type, strike, lots, sid
hedge_opened               — hedge wing: strike, sid
take_profit                — TP at 50% premium decay
stop_half                  — 30% stop: closed 50% lots
stop_all                   — 40% stop: closed all lots
trend_flip                 — bias sign reversed, legs closed+reopened
day_loss_cap_halt          — day P&L <= -15000, trading halted
all_legs_closed            — squareoff or full close
```

### 17.4 Backtest commands

```powershell
# Quick 30-day run (canonical config)
task backtest:strangle -- --config-file backtest/configs/strangle_nifty_hedged.yaml --days 30

# 2026 YTD
task backtest:strangle -- --config-file backtest/configs/strangle_nifty_hedged.yaml --from 2026-01-01 --out-dir backtest/runs

# Full 5-year (takes ~12 min)
task backtest:strangle -- --config-file backtest/configs/strangle_nifty_hedged.yaml --from 2021-09-01 --to 2026-06-25 --out-dir backtest/runs

# Trace mode (every-minute status.log per day)
task backtest:strangle -- --from 2026-06-20 --days 3 --trace
```

### 17.5 Reading the outputs

Each run in `backtest/runs/<run_id>/` contains:

| File | Contents |
|------|---------|
| `manifest.json` | Config + window + aggregate metrics + git SHA |
| `summary.csv` | One row/day: P&L, trades, drawdown, timing |
| `equity.csv` | Cumulative realized equity + peak + drawdown by day |
| `days/<date>/status.log` | Every-minute BarStatus: score, votes, legs, actions |
| `days/<date>/trades.csv` | Every fill: time, side, strike, qty, price, leg/day P&L |
| `days/<date>/legs.csv` | Closed-leg records: entry/exit/lots/pnl/reason |

### 17.6 Data prerequisites for backtest

VIX intraday data starts ~Aug 2021 → backtest window begins 2021-09-01.
Spot + options cover full Jan 2021 onwards.

```powershell
# If spot bars are missing
uv run python scripts/backfill_spot.py --from 2021-09-01 --only-missing

# If options bars are missing
uv run python scripts/backfill_options_gap.py --from 2021-09-01 --only-missing

# Audit coverage before a long run
uv run python scripts/audit_strangle_data.py
```

### 17.7 Config reference

| Role | NIFTY | BANKNIFTY | SENSEX |
|------|-------|-----------|--------|
| Backtest config | `backtest/configs/strangle_nifty_hedged.yaml` | `backtest/configs/strangle_banknifty_hedged.yaml` | `backtest/configs/strangle_sensex_hedged.yaml` |
| Live strategy YAML | `strategies/directional_strangle_nifty.yaml` | `strategies/directional_strangle_banknifty.yaml` | `strategies/directional_strangle_sensex.yaml` |
| strategy_id | `directional_strangle_nifty` | `directional_strangle_banknifty` | `directional_strangle_sensex` |
| option_segment | `NSE_FNO` | `NSE_FNO` | `BSE_FNO` |

Key knobs:

| Param | Value | Effect |
|-------|-------|--------|
| `otm_steps` | 2 | Sell 2 strikes OTM from ATM |
| `scale_lots` | 2 | All ratio-table values ×2 |
| `take_profit_pct` | 0.5 | Close leg when premium decays 50% |
| `pct_stop_half` | 0.30 | Close 50% lots when premium rises 30% |
| `pct_stop_all` | 0.40 | Close all when premium rises 40% |
| `hedge_enabled` | true | Buy far-OTM wing Rs 2–5 per short leg |
| `day_loss_limit` | 15000 | Halt if day P&L ≤ −Rs 15,000 |
| `entry_after_ist` | 10:15 | No entries before this |
| `squareoff_ist` | 15:10 | Hard flatten at/after this |
| `momentum_enabled` | false | Disabled (blew MaxDD 3.6× for tiny uplift) |
| `neutral_no_trade` | false | Trade neutral bucket as 3PE:3CE |

### 17.8 Parity improvements (non-blocking, follow-up OpenSpec: `live-directional-strangle-paper`)

Paper mode is fully working. These are refinements to close the gap with the backtest sim:

| Item | Backtest behaviour | Live behaviour today |
|------|--------------------|----------------------|
| Rollup | Re-strikes when premium < 20 | Holds cheap legs to squareoff |
| Stop-gate re-entry | 15 min cooldown after stop | Can re-enter immediately |
| Weekly Camarilla | `cam_weekly` wired from bars | `cam_weekly=None` (vote = 0) |
| PCR | Computed from OI totals | `pcr=None` (vote = 0) |
| Per-signal vote log | Full vote breakdown in status.log | `bias_evaluated` shows score only |

### 17.9 End-of-day checks

```powershell
# All orders placed today
curl "http://localhost:8000/api/v1/orders?today=1"

# All fills
curl http://localhost:8000/api/v1/trades

# P&L summary
curl http://localhost:8000/api/v1/portfolio/summary

# Paper journal (MongoDB)
docker exec -it pdp-mongo mongosh pdp --eval "db.paper_journal.find().sort({date:-1}).limit(1).pretty()"
```

### 17.10 Walk-forward reference

```powershell
# Walk-forward IS/OOS optimizer (reference only — 5yr full-window already validated)
task backtest:strangle:wf -- --from 2021-09-01 --to 2026-06-25 --out logs/wf.csv
```

---

## 18. Multi-Index Paper Trade — Day-of-Trading Guide

Three simultaneous DirectionalStrangle instances: **NIFTY + BANKNIFTY + SENSEX**.
Combined paper exposure only — no real orders until `LIVE=1` is set.

---

### 18.1 Pre-market startup (before 09:00 IST)

**Step 1 — Databases**
```powershell
task db:up        # postgres:5432 + redis:6379 + mongo:27017
task db:migrate   # safe to re-run; no-op if already current
```

**Step 2 — Start API (paper mode)**
```powershell
task dev          # http://localhost:8000  (LIVE is unset = paper)
```

**Step 3 — Confirm all 3 strategies loaded**
```powershell
curl http://localhost:8000/api/v1/strategies
```
Expected (all 3 with `"mode": "paper"`, `"status": "active"`):
```json
[
  {"id": "directional_strangle_nifty",      "mode": "paper", "status": "active"},
  {"id": "directional_strangle_banknifty",  "mode": "paper", "status": "active"},
  {"id": "directional_strangle_sensex",     "mode": "paper", "status": "active"}
]
```
If any strategy is missing → check the API logs for import errors.

**Step 4 — Verify instruments are loaded for today's expiry**
```powershell
# NIFTY options (NSE_FNO, next Tuesday expiry)
curl "http://localhost:8000/api/v1/instruments/search?underlying=NIFTY&limit=5"

# BANKNIFTY options (NSE_FNO, next Thursday expiry)
curl "http://localhost:8000/api/v1/instruments/search?underlying=BANKNIFTY&limit=5"

# SENSEX options (BSE_FNO, next Friday expiry)
curl "http://localhost:8000/api/v1/instruments/search?underlying=SENSEX&limit=5"
```
If any returns empty → the scrip master hasn't been loaded for today.
Fix: the API auto-loads instruments on startup when `DHAN_CLIENT_ID` is set.
Manual trigger: `curl -X POST http://localhost:8000/api/v1/instruments/reload`

### 18.2 Environment variables required

| Variable | Paper value | Notes |
|----------|-------------|-------|
| `LIVE` | _(unset or `0`)_ | **Never** set to `1` during paper runs |
| `DHAN_CLIENT_ID` | your client id | Required for live Dhan tick feed |
| `DHAN_ACCESS_TOKEN` | your token | Required for live Dhan tick feed |
| `BROKER` | `paper` | Default; implicit when LIVE is not set |

Without `DHAN_CLIENT_ID`, the tick feed uses a mock source — no real market data, bias scores stay 0.

---

### 18.3 Trading hours monitoring (10:15–15:10 IST)

**Quick overview — all 3 strategies at once**
```powershell
# All running strategies + their heartbeat fields
curl http://localhost:8000/api/v1/strategies
```

**Per-strategy status (bucket, score, open legs, day P&L)**
```powershell
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_nifty"
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_banknifty"
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_sensex"
```
Key fields to watch:
- `bucket` — current bias bucket (most_bull / neutral / most_bear etc.)
- `score` — −1 to +1 (negative = bearish; positive = bullish)
- `n_open_shorts`, `n_open_hedges` — should be > 0 after first entry after 10:15
- `day_pnl` — paper P&L (realized + unrealized)
- `done_for_day` — becomes `true` after 15:10 or day-loss-cap hit

**Live activity feed (last 20 events for each)**
```powershell
curl "http://localhost:8000/api/v1/strangle/activity?strategy_id=directional_strangle_nifty&n=20"
curl "http://localhost:8000/api/v1/strangle/activity?strategy_id=directional_strangle_banknifty&n=20"
curl "http://localhost:8000/api/v1/strangle/activity?strategy_id=directional_strangle_sensex&n=20"
```
Normal pattern after 10:15: `bias_evaluated → leg_status` repeating every 5m.
On entry: `leg_open (short) → leg_open (hedge)`.
On exit: `leg_close` or `take_profit` or `stop_all`.

**Tail the structlog (all strategies in one stream)**
```powershell
# In a separate terminal — all strategy events in real time
task dev 2>&1 | Select-String "bias_evaluated|leg_open|leg_close|take_profit|stop_all|day_loss_cap|square_off"
```

**Watch the per-strategy daily log files**
```powershell
# One per strategy, keyed by strategy_id
Get-Content "backend\logs\directional_strangle_nifty\$(Get-Date -Format 'yyyy-MM-dd').log" -Wait -Tail 5
Get-Content "backend\logs\directional_strangle_banknifty\$(Get-Date -Format 'yyyy-MM-dd').log" -Wait -Tail 5
Get-Content "backend\logs\directional_strangle_sensex\$(Get-Date -Format 'yyyy-MM-dd').log" -Wait -Tail 5
```

---

### 18.4 Quick debug during trading hours

**Problem: strategy shows no activity after 10:15**

```powershell
# Check for bias_evaluated events
curl "http://localhost:8000/api/v1/strangle/activity?strategy_id=directional_strangle_nifty&n=5"
# If empty → strategy may not be receiving bars
```

Cause A — Tick feed not connected (no `DHAN_CLIENT_ID`/token):
```powershell
curl http://localhost:8000/healthz
# Look for: "market_feed": "connected" vs "disconnected"
```

Cause B — Indicators not warmed (strategy logs `strategy_warmup_warning`):
```powershell
# Search today's log for warmup issues
Select-String "warmup" "backend\logs\directional_strangle_nifty\$(Get-Date -Format 'yyyy-MM-dd').log"
```
Normal: warmed_timeframes=[5m,15m,1h]. If missing any TF → indicator engine hasn't received enough bars yet (resolves within 2–3 bars of session open).

Cause C — Wrong security_id in watchlist (bars arriving under different sid):
Check that `underlying_security_id` in the YAML matches what the tick feed sends (NIFTY=13, BANKNIFTY=25, SENSEX=51).

---

**Problem: SENSEX shows `no_instrument_for_strike`**

SENSEX options are on `BSE_FNO`. Verify instruments are loaded:
```powershell
curl "http://localhost:8000/api/v1/instruments/search?underlying=SENSEX&limit=3"
# If empty → BSE scrip master not loaded for today
curl -X POST http://localhost:8000/api/v1/instruments/reload
```

---

**Problem: one strategy hit day_loss_cap and stopped**

```powershell
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_banknifty"
# Look for: "done_for_day": true
```
Other two strategies continue independently — each has its own loss cap.
To confirm which event triggered it:
```powershell
curl "http://localhost:8000/api/v1/strangle/activity?strategy_id=directional_strangle_banknifty&n=10"
# Look for: {"event_type": "day_loss_cap", ...}
```

---

**Problem: API crashed / need to restart mid-day**

```powershell
# Stop API (Ctrl+C in the dev terminal, or kill process)

# Restart — strategies resume from instruments table (open positions recovered via recovery.py)
task dev

# Verify all 3 reloaded
curl http://localhost:8000/api/v1/strategies

# Check each strategy re-subscribed to options (should show existing legs in memory)
curl "http://localhost:8000/api/v1/strangle/legs?strategy_id=directional_strangle_nifty"
```

> **Note:** On restart the in-memory `_activity` ring buffer is empty (events since restart only). The daily log file persists — check it for pre-restart history.

---

### 18.5 End-of-day checks (after 15:10 IST)

```powershell
# Confirm all 3 strategies squared off
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_nifty"
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_banknifty"
curl "http://localhost:8000/api/v1/strangle/status?strategy_id=directional_strangle_sensex"
# Expect: "done_for_day": true, "n_open_shorts": 0, "n_open_hedges": 0

# Day P&L for each
curl "http://localhost:8000/api/v1/strangle/stats?strategy_id=directional_strangle_nifty"
curl "http://localhost:8000/api/v1/strangle/stats?strategy_id=directional_strangle_banknifty"
curl "http://localhost:8000/api/v1/strangle/stats?strategy_id=directional_strangle_sensex"

# All paper orders placed today (all strategies)
curl "http://localhost:8000/api/v1/orders?today=1"

# Portfolio summary
curl http://localhost:8000/api/v1/portfolio/summary

# Paper journal in MongoDB
docker exec -it pdp-mongo mongosh pdp --eval "db.paper_journal.find().sort({date:-1}).limit(3).pretty()"
```

### 18.6 Backtest commands (3-index)

```powershell
# Run any single index (replace config file)
task backtest:strangle -- --config-file backtest/configs/strangle_nifty_hedged.yaml --days 30
task backtest:strangle -- --config-file backtest/configs/strangle_banknifty_hedged.yaml --from 2021-08-04 --to 2024-12-31 --out-dir backtest/runs
task backtest:strangle -- --config-file backtest/configs/strangle_sensex_hedged.yaml --from 2024-01-01 --out-dir backtest/runs
```

---

### 18.7 Concurrent margin estimate (all 3 indices live)

**Methodology:** Each strategy opens up to `max(ratio_table_sum) × scale_lots` short lots in a single entry cycle. The worst-case (neutral bucket [3,3] × scale_lots=2) is 6 PE + 6 CE = 12 lots per index. Short OTM option SPAN margin is roughly ₹7,000–20,000/lot depending on the index; long hedge legs provide ~20–30% SPAN offset.

| Index | lot_size | Max short lots | Contracts | SPAN est./lot | Gross SPAN | Net (with hedge) |
|-------|----------|---------------|-----------|--------------|------------|-----------------|
| NIFTY | 65 | 12 | 780 | ~₹8,000 | ~₹96,000 | **~₹70,000** |
| BANKNIFTY | 30 | 12 | 360 | ~₹17,000 | ~₹2,04,000 | **~₹1,50,000** |
| SENSEX | 20 | 12 | 240 | ~₹15,000 | ~₹1,80,000 | **~₹1,30,000** |
| **Total** | | **36 lots** | **1,380** | | | **~₹3,50,000** |

**Key findings:**
- Combined peak margin ~₹3.5–5L — well within a standard Dhan F&O account (typical ₹10–25L exposure limit).
- NIFTY and BANKNIFTY are both on NSE_FNO; SENSEX is on BSE_FNO. No cross-exchange offset applies.
- SEBI client-level position limits for index options (NIFTY: 15,000 contracts; BANKNIFTY: 12,000; SENSEX: BSE equivalent) are far above our 780/360/240 contract peaks — no regulatory breach risk.
- Each strategy has its own `day_loss_limit: 50,000` hard cap. Worst-case combined daily loss = ₹1.5L (3 × ₹50,000). A ₹10L account can absorb this comfortably.
- The three indices have low intraday return correlation (SENSEX on BSE moves independently on some sessions), reducing simultaneous large-loss days.

**Minimum recommended account size:** ₹7–10L (₹3.5L for peak margin + ₹3.5L buffer for adverse MTM before stops trigger).

---

## 19. Strangle — Weekly Parity Check Procedure

Run this after any live trading week to verify paper P&L matches backtest replay.

### 19.1 Run backtest for the same period

```powershell
# Replace YYYY-MM-DD with the Monday of the week
task backtest:strangle -- --from YYYY-MM-DD --to YYYY-MM-DD --trace
```

This writes `backtest/runs/<run_id>/days/<date>/status.log` with one BarStatus line per bar.

### 19.2 Compare with live bias_evaluated events

The live daily log is at `backend/logs/directional_strangle/<YYYY-MM-DD>.log`.

```powershell
# Extract live bias_evaluated lines
grep '"event_type": "bias_evaluated"' backend/logs/directional_strangle/YYYY-MM-DD.log | python -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print(d['ist_time'], d['bucket'], round(d['score'], 3), dict(sorted(d.get('votes', {}).items())))
"

# Compare with backtest status.log
cat backtest/runs/<run_id>/days/YYYY-MM-DD/status.log | head -30
```

### 19.3 What to look for

| Match | Verdict |
|-------|---------|
| Bucket agrees on 90%+ of bars | Parity OK |
| Score differs by < 0.05 per bar | Minor input variance (normal) |
| Bucket differs by > 10% of bars | Investigate; check missing signals (cam_weekly, pcr) |
| Trades fire at same bars | Execution matches |
| P&L within ±5% of backtest | Expected slippage |

### 19.4 Common parity gaps

| Gap | Root cause | Fix |
|-----|-----------|-----|
| `cam_weekly` always None in live | 1w bar not yet supported | Track in `claude-ops-agents` chunk |
| `pcr` always None in live | No indicator engine method | Track in `claude-ops-agents` chunk |
| Score differs by ~0.1 | ORB from 15m vs exact 9:15 bar | Acceptable |

---

## 20. Strangle — Canonical Event Types Reference

Every significant strategy action emits a structured JSON event to both structlog and the
daily log file (`backend/logs/directional_strangle/<YYYY-MM-DD>.log`).

### 20.1 Common base fields (on every event)

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | str | One of the types below |
| `strategy_id` | str | Always `directional_strangle` |
| `snapshot_date` | str | IST date of the current session (YYYY-MM-DD) |
| `ist_time` | str | IST ISO timestamp of emission |
| `underlying` | str | Always `NIFTY` |
| `score` | float | Current bias score (−1 to +1) |
| `bucket` | str or None | Current bucket (e.g. `most_bull`) |

### 20.2 Event type catalogue

| Event type | When emitted | Key extra fields |
|-----------|-------------|-----------------|
| `bias_evaluated` | Every 5m bar (trading window) | `votes`, `gated`, `reason`, `shorts`, `momentum` |
| `leg_status` | After every `bias_evaluated` | `legs[]` (sid, opt_type, strike, lots, entry_price, ltp, mtm, is_hedge) |
| `leg_open` | Short or hedge opened | `sid`, `opt_type`, `strike`, `lots`, `entry_price`, `is_hedge`, `is_momentum` |
| `leg_close` | Short, hedge, or momentum closed | `sid`, `opt_type`, `strike`, `reason` |
| `take_profit` | TP at 50% premium decay | `sid`, `ltp`, `entry`, `opt_type`, `strike` |
| `stop_half` | 30% premium rise — partial close | `sid`, `ltp`, `remaining`, `opt_type`, `strike` |
| `stop_all` | 40% premium rise — full close | `sid`, `ltp`, `entry`, `opt_type`, `strike` |
| `day_loss_cap` | Day P&L ≤ −Rs 15,000 | `day_pnl` |
| `rolled` | Premium decayed < Rs 20; reopen | `opt_type`, `old_strike`, `old_ltp`, `new_strike`, `new_ltp`, `lots`, `result` |
| `stop_gate_wait` | Re-entry blocked after stop | `opt_type`, `exit_px`, `ltp`, `n_below` |
| `bucket_change` | Bias bucket shifted | `old_bucket`, `new_bucket` |
| `square_off` | 15:10 IST hard flatten | `reason` |

### 20.3 Reading the daily log

```powershell
# Pretty-print today's events
python -c "
import json, sys
with open('backend/logs/directional_strangle/YYYY-MM-DD.log') as f:
    for line in f:
        e = json.loads(line)
        t = e.get('ist_time', '')[-8:]  # HH:MM:SS
        print(f\"{t}  {e['event_type']:<20}  {e.get('bucket',''):>12}  score={e.get('score', '')}\")
"
```

### 20.4 Invoke the Claude review skill after a session

```
/strangle:review
```

The skill reads today's log, parses all events, and produces: session summary, bias
timeline, per-signal vote analysis, trades table, and improvement suggestions.

---

## 21. Unified Log Pipeline (OpenSearch)

Every log in the system — API request logs, strategy events, journal flushes, backtest
results, and Flutter UI logs — auto-ships to OpenSearch in realtime through one pipeline.
Logs land in `pdp-logs-*` (universal) and high-value events in typed analytics indices,
all segregated by a `source` field. Disabled by default (`OPENSEARCH_ENABLED=false`).

### 18.1 Settings (add to `backend/.env`)

```env
OPENSEARCH_ENABLED=true
OPENSEARCH_URL=http://localhost:9200        # or AWS OpenSearch endpoint in prod
OPENSEARCH_USER=                           # leave blank for dev (security disabled)
OPENSEARCH_PASSWORD=
OPENSEARCH_VERIFY_CERTS=false              # true for prod (AWS)
OPENSEARCH_INDEX_PREFIX=pdp               # prefix for all index names
OPENSEARCH_BULK_INTERVAL=2.0              # flush interval in seconds
OPENSEARCH_BULK_MAX=500                   # max docs per bulk request
OPENSEARCH_QUEUE_MAX=10000                # in-memory queue cap (drop-on-full)
OPENSEARCH_LOG_LEVEL=INFO                 # min level shipped to pdp-logs-*
```

### 18.2 Start + bootstrap

```bash
# Start OpenSearch (and optionally Dashboards at :5601)
task search:up

# Apply index templates + import 8 dashboards (idempotent, safe to re-run)
task search:init
```

### 18.3 Indices

| Index pattern | Source | What |
|---|---|---|
| `pdp-logs-*` | all | Every structlog record + Flutter UI logs. Filter by `source` field: `api`, `strategy`, `orders`, `market`, `ui`, … |
| `pdp-strangle-events-*` | strategy | Per-bar events: bias evaluations, leg open/close/stop |
| `pdp-trades-*` | journal | Individual fills / order executions |
| `pdp-journal-*` | journal | Daily stats: realized P&L, win/loss counts, premium sold/bought |
| `pdp-backtest-runs-*` | backtest | Per-run metrics (net, PF, Sharpe, MaxDD, verdict) |
| `pdp-backtest-days-*` | backtest | Per-day equity curve within a run |
| `pdp-backtest-trades-*` | backtest | Simulated fills inside a backtest |

All indices are monthly date-suffixed (`pdp-logs-2026.06`) and use `dynamic: false` mappings.

### 18.4 Dashboards

Open `http://localhost:5601` after `task search:up && task search:init`. Eight dashboards
are pre-imported:

| # | Dashboard | Key question |
|---|---|---|
| 1 | Unified Log Explorer | What's happening across all sources right now? |
| 2 | Live Strategy Session | How did NIFTY and the strangle behave today? |
| 3 | Trade Blotter & P&L | What fills happened and what's the realized P&L? |
| 4 | Journal Analytics | Daily/weekly P&L trends and win rate? |
| 5 | Backtest Explorer | Which run is the best config? |
| 6 | Bias Effectiveness | Is the bucket signal actually predictive? |
| 7 | Live ↔ Backtest Parity | Does live performance match backtest expectations? |
| 8 | UI Health | Are there Flutter errors spiking on a specific screen? |

### 18.5 Claude session review

After a live session:

```bash
GET /api/v1/analysis/session?date=YYYY-MM-DD&strategy_id=directional_strangle
```

Returns a bar-anchored JSON narrative. Feed it to Claude with the prompt at
`backend/scripts/analysis/strangle_review_prompt.md` for a structured verdict.

### 18.6 Hot-path safety

- **OS down = no-op**: if OpenSearch is unreachable the indexer logs one warning and
  discards the queue. All stdout/file logging and JSONL/Mongo sources of truth are
  unaffected.
- **Queue pressure**: if the in-memory queue fills (> `OPENSEARCH_QUEUE_MAX` docs) new
  records are dropped silently. Check `indexer.dropped` metric in the `/healthz` endpoint.
- **No feedback loop**: the `pdp.observability` logger itself binds `_no_ship=True` so
  indexer log records are never re-enqueued.

---

## 19. Market Feed Resilience (market-feed-resilience)

### Stale-feed watchdog

A `FeedWatchdog` runs alongside the live Dhan tick feed (started only when `DHAN_CLIENT_ID` is set).
Every second it checks whether any tick arrived within `FEED_STALE_SECONDS`.  If no tick comes
during market hours (09:15–15:35 IST) it logs a `feed_stale` warning and forces a reconnect on
the adapter by closing the underlying WebSocket — the exponential-backoff connection loop then
re-establishes the feed automatically.

This does NOT auto-evict subscriptions (a silent underlying is legitimate).

```env
FEED_STALE_SECONDS=60         # seconds without a tick before watchdog fires
FEED_RECONNECT_BASE_DELAY=1.0 # initial backoff in seconds
FEED_RECONNECT_MAX_DELAY=30.0 # cap for exponential reconnect backoff
```

### Backfill interior-gap protection

`gap_backfill.py:fill_day` now runs an interior-gap check on the spot minute series before
persisting any option bars.  If the spot data has an empty window between two non-empty windows,
the whole day is skipped and a `backfill_interior_gap` warning is logged — the day remains
visible to `days_missing` for retry in the next scheduled scan.

Leading or trailing empty windows are *not* treated as gaps (pre-open / post-close windows are
naturally empty).

### Scrip-master daily refresh

```env
SCRIP_REFRESH_ENABLED=false  # set to true to activate
SCRIP_REFRESH_TIME=08:45     # IST HH:MM — fires once per day before market open
```

When enabled, `ScripRefreshScheduler` downloads the Dhan scrip master at the configured time,
upserts it into the `instruments` PG table (including the new `freeze_qty` column), and writes a
filtered snapshot CSV to `data/masters/<YYYY-MM-DD>.csv` for historical backtest lookups.
Failures log `scrip_refresh_failed` and retry the next day without blocking startup.

---

## 20. Ops Safety Net (ops-safety-net)

### Global exception handler

All unhandled exceptions in FastAPI routes are caught by a single `@app.exception_handler` and
returned as:
```json
{"error": {"type": "ExceptionClassName", "message": "...", "request_id": "..."}}
```
HTTP status is always 500 for unhandled exceptions; `HTTPException` keeps its own status code.
The traceback is logged once at ERROR level (also lands in `errors.jsonl`).

### errors.jsonl ERROR sink

Every ERROR-level log record is appended as one JSON line to `ERRORS_JSONL_PATH` (default
`logs/errors.jsonl`).  This file is the fast local incident view — open it first during an
incident before querying OpenSearch.  On startup the file is truncated to `ERRORS_JSONL_MAX_LINES`
most-recent lines.  Write failures are swallowed (never break request handling).

```env
ERRORS_JSONL_PATH=logs/errors.jsonl
ERRORS_JSONL_MAX_LINES=1000
```

### Sensitive-data redaction

`LOG_REDACTION_ENABLED=true` (default) enables a `SensitiveDataFilter` structlog processor that
runs before OpenSearch + JSONRenderer.  It redacts:
- Keys matching `access_token`, `api_key`, `password`, `bearer` (case-insensitive) → `***`
- Values matching JWT pattern `eyJ...` → `***`

The `app_starting` banner no longer leaks `DHAN_ACCESS_TOKEN` in logs.

```env
LOG_REDACTION_ENABLED=true
```

### Feed-stale safe-halt

When `feed_stale` persists longer than `FEED_STALE_HALT_SECONDS` (default 180s):
- `FeedStaleHalt.live_blocked = True`
- All new **live** orders are rejected with reason `feed_stale_halt: live entries blocked until operator clears`
- **Paper orders are unaffected** (no real money at risk)
- Recovery does **not** auto-resume — operator must call `POST /risk/kill-switch/clear-feed-halt` (or restart the service)

```env
FEED_STALE_HALT_SECONDS=180
```

---

## 21. Order Pre-Flight Checks (broker-order-safety)

Every order passes a pre-flight gate in `OrderRouter._preflight` before reaching the broker.

### What runs

| Check | When it fires | Setting |
|-------|--------------|---------|
| Lot-size multiple | Always (if instrument known) | `ORDER_PREFLIGHT_ENABLED=true` |
| Freeze-qty limit | Always (instrument col or settings map) | `ORDER_PREFLIGHT_ENABLED=true` |
| Pre-trade charge estimate | Always (uses `ChargesCalculator`) | `ORDER_PREFLIGHT_ENABLED=true` |
| Live Dhan margin check | Live + credentialed only | `MARGIN_CHECK_ENABLED=true` |

### Settings reference

```env
ORDER_PREFLIGHT_ENABLED=true      # master switch
MARGIN_CHECK_ENABLED=false        # live Dhan margin API (enable after creds confirmed)
MARGIN_BUFFER_PCT=5.0             # block if required > available × (1 - buffer/100)
MARGIN_FAILOPEN=false             # fail-closed in live; true = advisory on API error
FREEZE_QTY_BY_UNDERLYING='{"NIFTY":1800,"BANKNIFTY":900,"SENSEX":1000}'
```

### Paper vs live behaviour

- **Paper mode**: violations are logged as `order_preflight_advisory` warnings; the order is
  **not** blocked. This lets you observe violations during paper runs without interrupting them.
- **Live mode**: any violation → order is set to `REJECTED` before reaching the broker.

### Reading a blocked order

An order rejected by preflight has `status=REJECTED` and a `reject_reason` like:
```
qty 75 not a multiple of lot_size 75; insufficient margin: required 82500.00 > available 60000.00 (buffer 5.0%)
```

Violations are also logged as `order_preflight_failed` at INFO level with the full list.

### Enabling the Dhan margin check

1. Ensure `BROKER_SYNC_ENABLED=true` and a sync has run (populates `broker_funds.available_balance`).
2. Set `MARGIN_CHECK_ENABLED=true` in `.env`.
3. Restart the API.
4. The next paper run will log `margin_required` on every `order_preflight_ok` event.
5. Promote to live (`LIVE=1`) only after paper validation passes.

---

## 19. Strangle Live-Paper Hardening (change `strangle-live-paper-hardening`)

Fixes applied 2026-06-29 based on the first 3-index paper session. This section explains the
new mechanisms so you know what to look for in the logs.

### 19.1 LTP delivery to strategy (R1)

**Problem:** option-leg `ltp/mtm` were always `null` because `StrategyHost.on_tick()` only
dispatched ticks matching the static YAML watchlist, which contains only the index SID.
Option SIDs are subscribed dynamically at runtime via `ctx.market.subscribe()`.

**Fix:** each running strategy now maintains a `dynamic_sids: set[str]` tracked inside
`_StrategyState`. `MarketControl.subscribe()` adds the SID; `on_tick()` dispatches if the SID
is in either the static watchlist or the dynamic set. Leg-close paths call `unsubscribe()`;
`stop()` clears the set.

**Verify in log:** `leg_status` events should show `ltp` and `mtm` as non-null floats for
every open leg from the first 5m bar after entry.

### 19.2 Paper fill integrity (R2)

**Problem:** `avg_price = 0` was stored when the MARKET order's pub/sub tick hadn't arrived
yet. Closing the position then computed `(0 − close_px) × qty` → fabricated loss.

**Fixes (dual-defence):**
- `PaperBroker.add_order()` now reads `ltp:{sid}` from Redis immediately and fills on the
  spot for MARKET orders if a price is cached (path: router sets `ltp:` cache on every tick).
- `upsert_position` guards `old_avg == 0`: skips the realized-P&L computation and logs
  `zero_avg_realized_skipped` warning instead of computing a nonsense number.

**Verify in log:** no `zero_avg_realized_skipped` warnings. All `leg_open` events show
`entry_price > 0`, including hedges.

### 19.3 Day-loss halt persistence (R5)

**Problem:** restarting the API on the same calendar day after `day_loss_cap` fired allowed
re-entry, because `_done_for_day` resets to `False` on `on_init`.

**Fix:** on `day_loss_cap`, the strategy writes a Redis key
`halt:{strategy_id}:{YYYY-MM-DD}` (IST date) with 86400s TTL. On the first bar of each day,
the strategy reads the key (`_maybe_restore_halt_marker`). If the key exists for today, it
sets `_done_for_day = True` — the session is over. The marker is cleared automatically by the
TTL and by `_maybe_reset_day` on IST date rollover.

**Verify:** after a simulated `day_loss_cap` (set `day_loss_limit=1` briefly), stop and
restart. The log should show `halt_marker_restored` at the first bar, and no new leg_open
events for the rest of that calendar day.

### 19.4 Bias signal set (R3)

**PCR** — now read from `OptionsHub.get_pcr(underlying)` at each bias evaluation. PCR is
computed from chain OI during each option-chain poll (only available when
`OptionsChainPoller` is running, i.e., `LIVE=1`). In paper mode, PCR stays `None` and the
vote is correctly skipped by the bias engine.

**VWAP from futures** — the NIFTY/BANKNIFTY/SENSEX index has no traded volume; `vwap` from
the spot SID is always `None`. Set `futures_security_id` in the strategy YAML params to the
Dhan SID of the front-month index future (update monthly). Add a watchlist entry for that SID
with `timeframes: [5m]` and `indicators: [{family: vwap}]` so bars flow to the indicator
engine.

**EMA warmup (15m / 1H)** — warmup now fetches multiple prior sessions rather than just one:
6 calendar days for 15m (covering 2 sessions × 25 bars = 50 bars → EMA(50) seeded) and 14
calendar days for 1H (covering ~8 sessions × 7 bars = 56 bars → EMA(50) seeded). Confirmed
by `indicator_warmup_done` log at startup — check the `bars_fed` field.

**cam_weekly** — weekly Camarilla requires `1w` bar support in the bar aggregator (not yet
added). The `cam_weekly_missing` debug log fires once per strategy session; this is expected
until the bar aggregator adds `1w` support.

### 19.5 Bucket-change hysteresis (R4)

**Problem:** a single 5m-bar bucket flip immediately closed and reopened all legs — 3
reversals in 15 min were observed on BANKNIFTY.

**Fix:** `bucket_confirm_bars` param (default 2). A new bucket must persist for N consecutive
5m bars before the strategy acts. The pending bucket and counter reset if the bar reverts.

**Tune:** if the market is trending strongly, you may want to lower to 1. The backtest used
the default threshold, so 2 is validated over 5yr.

### 19.6 Configuring futures SID for VWAP

To enable real VWAP for NIFTY:

1. Look up the front-month NIFTY futures SID in `data/masters/<YYYY-MM-DD>.csv` (the column
   is `SEM_SMST_SECURITY_ID`; filter for `SM_SYMBOL_NAME = NIFTY` and the nearest monthly
   expiry).
2. Add to `strategies/directional_strangle_nifty.yaml`:
   ```yaml
   watchlist:
     # ... existing spot entry ...
     - security_id: "<FUTURES_SID>"
       exchange_segment: NSE_FNO
       timeframes: [5m]
       indicators:
         - family: vwap

   params:
     # ... existing params ...
     futures_security_id: "<FUTURES_SID>"
   ```
3. Repeat monthly when the front-month rolls (last Thursday of the expiry month).

Until configured, VWAP remains `None` and the vote is skipped (safe; no fabricated signal).

Kill API: `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force`