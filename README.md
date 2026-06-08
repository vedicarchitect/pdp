# PDP — OpenSpec-Driven Trading & Investment Platform

A self-hosted, **paper-first** trading and investment platform for intraday, positional, and portfolio management on Indian exchanges (NSE/BSE/MCX via Dhan). Every capability is spec-driven: no implementation without an OpenSpec proposal.

**Key Principles:**
- 📋 **Spec-first**: All features defined in `openspec/` before coding
- 📄 **Paper-engine default**: Live trading requires `LIVE=1` + broker config
- ⚡ **Latency budget**: Tick → WebSocket p99 ≤ 50ms
- 🗄️ **DB separation**: PostgreSQL (ACID ledger), MongoDB (time-series warehouse), Redis (hot cache)
- 🔍 **Structured logging**: JSON logs via structlog

---

## Quickstart

### Prerequisites
- **Python 3.13+** (check with `python --version`)
- **uv** package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **Docker & Docker Compose** for services
- **Node.js 18+** for frontend/OpenSpec CLI (optional)

### 1. Initial Setup

```bash
# Clone and navigate
cd PDP

# Copy environment template
cp .env.example .env

# Install Python dependencies
uv sync

# Optional: install dev dependencies (for testing, linting, type-checking)
uv sync --group dev
```

### 2. Start Infrastructure

```bash
# Bring up PostgreSQL 16, Redis 7, MongoDB 7
docker compose up -d postgres redis mongo

# Verify containers are running
docker compose ps
```

### 3. Initialize Database

```bash
# Run all migrations
uv run alembic upgrade head

# Check migration status
uv run alembic current
```

### 4. Run the API Server

```bash
# Start FastAPI with hot reload
uv run uvicorn pdp.main:app --reload

# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs (Swagger UI)
# Health check: http://localhost:8000/healthz
```

### 5. (Optional) Start Frontend Dev Server

```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
# → Frontend at http://localhost:5173
```

---

## Development Workflow

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/pdp --cov-report=term-report

# Run specific test file
uv run pytest tests/positional/test_aggregation.py

# Run tests matching a pattern
uv run pytest -k "test_greek" -v
```

### Type Checking & Linting

```bash
# Type check (strict mode on src/pdp/)
uv run pyright

# Format code with ruff
uv run ruff format src/ tests/

# Lint and show violations
uv run ruff check src/ tests/

# Fix auto-fixable violations
uv run ruff check src/ tests/ --fix
```

### Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "add positions table"

# Review the migration file in alembic/versions/
# Then apply it:
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1

# Check current migration version
uv run alembic current

# See migration history
uv run alembic history
```

### Using Task Runner

```bash
# List available tasks
task --list

# Run a task (examples vary by Taskfile.yml)
task build
task test
```

---

## Project Structure

```
PDP/
├── openspec/                    # Spec-driven workflow
│   ├── project.md               # Tech stack & architecture (READ THIS)
│   ├── specs/                   # Archived, finalized capabilities
│   │   ├── add-platform-skeleton/
│   │   ├── add-instrument-registry/
│   │   └── ...
│   └── changes/                 # In-flight proposals
│       ├── add-positional-monitor/
│       └── ...
│
├── src/pdp/                     # Python package (strict type-checking)
│   ├── main.py                  # FastAPI app & route mounting
│   ├── settings.py              # Pydantic settings (env-driven config)
│   ├── logging.py               # structlog setup
│   ├── cli.py                   # Click CLI entry point (pdp command)
│   ├── db/                      # Database layer
│   │   ├── models.py            # SQLAlchemy ORM models
│   │   ├── session.py           # Async session factory
│   │   └── ...
│   ├── market/                  # Market data & indicators
│   │   ├── feed.py              # Broker WS adapter (Dhan)
│   │   ├── bars.py              # OHLCV bar aggregation
│   │   ├── router.py            # Tick routing & caching
│   │   └── ...
│   ├── orders/                  # Order routing & execution
│   │   ├── models.py            # Order/trade/position models
│   │   ├── paper.py             # Paper trading engine
│   │   ├── broker.py            # Dhan broker adapter
│   │   └── ...
│   ├── portfolio/               # Holdings & P&L
│   │   ├── service.py           # Portfolio MTM calculation
│   │   └── ...
│   ├── strategy/                # Pluggable strategy host
│   │   ├── base.py              # Strategy interface
│   │   └── manager.py           # Strategy lifecycle
│   └── api/                     # FastAPI routes
│       ├── orders.py            # POST /orders, PATCH /orders/{id}
│       ├── market.py            # GET /instruments, /bars, /chains
│       ├── portfolio.py         # GET /portfolio, /positions
│       └── websocket.py         # WS /ws/market, /ws/orders
│
├── frontend/                    # Vite + React 19 frontend
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── hooks/               # Custom React hooks
│   │   ├── routes/              # TanStack Router pages
│   │   └── App.tsx
│   ├── vite.config.ts
│   └── package.json
│
├── tests/                       # pytest suite (async-aware)
│   ├── conftest.py              # Shared fixtures
│   ├── positional/              # Positional trading tests
│   ├── orders/                  # Order execution tests
│   └── ...
│
├── alembic/                     # SQLAlchemy migration tool
│   ├── versions/                # Migration files
│   └── env.py                   # Alembic config
│
├── CLAUDE.md                    # Agent guidance (spec-first, paper-first)
├── docker-compose.yml           # PostgreSQL, Redis, MongoDB
├── Taskfile.yml                 # Task runner commands
├── pyproject.toml               # uv config, dependencies, tool settings
├── .env.example                 # Environment template
└── README.md                    # This file
```

---

## Core APIs

### Market Data

```bash
# Get all tradable instruments
curl http://localhost:8000/instruments

# Get instrument by symbol
curl "http://localhost:8000/instruments?symbol=NIFTY50"

# Stream market data (WebSocket)
wscat -c ws://localhost:8000/ws/market
# Subscribe to ticker updates
{"action": "subscribe", "symbols": ["NSE:NIFTY50", "NSE:BANKNIFTY"]}
```

### Orders & Positions

```bash
# Place an order (paper engine by default)
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NIFTY50",
    "side": "BUY",
    "quantity": 1,
    "order_type": "MARKET"
  }'

# Get open positions
curl http://localhost:8000/positions

# Get order history
curl http://localhost:8000/orders

# Modify an order
curl -X PATCH http://localhost:8000/orders/{order_id} \
  -H "Content-Type: application/json" \
  -d '{"quantity": 2}'

# Cancel an order
curl -X DELETE http://localhost:8000/orders/{order_id}
```

### Portfolio

```bash
# Get portfolio summary
curl http://localhost:8000/portfolio

# Get holdings (equity + MF)
curl http://localhost:8000/portfolio/holdings

# Get real-time P&L
curl http://localhost:8000/portfolio/pnl
```

### Options Analytics

```bash
# Get option chain for NIFTY50 (all strikes, current expiry)
curl "http://localhost:8000/chains?symbol=NIFTY50"

# Get Greeks for specific expiry
curl "http://localhost:8000/chains?symbol=BANKNIFTY&expiry=2026-06-25"
```

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# App
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/pdp

# Cache (Redis)
REDIS_URL=redis://localhost:6379/0

# Warehouse (MongoDB)
MONGODB_URL=mongodb://localhost:27017/pdp

# Broker (Dhan)
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
LIVE=0  # 0 = paper engine, 1 = live trading

# API
API_BIND_HOST=0.0.0.0
API_BIND_PORT=8000
API_RELOAD=true
```

---

## OpenSpec Workflow

This project is **spec-first**. All features must start with an OpenSpec proposal.

```bash
# 1. List active changes
npx -y @fission-ai/openspec list

# 2. Show details of a change
npx -y @fission-ai/openspec show add-positional-monitor

# 3. Validate all specs
npx -y @fission-ai/openspec validate --all --strict

# 4. Create a new change (start a new feature)
npx -y @fission-ai/openspec new <change-id>
# Creates: openspec/changes/<change-id>/design.md, specs/, tasks.md

# 5. After implementation, archive the change
npx -y @fission-ai/openspec archive <change-id>
# Moves specs to openspec/specs/<capability>/
```

See [openspec/project.md](openspec/project.md) for architecture, tech stack, and conventions.

---

## Broker Setup (Dhan)

### Paper Trading (Default)

No setup needed—orders route to the paper engine. Check `src/pdp/orders/paper.py`.

### Live Trading

⚠️ **Paper is the default.** To enable live trading:

1. **Get credentials from Dhan:**
   - Sign up at [dhanhq.co](https://www.dhanhq.co/)
   - Generate API credentials in dashboard

2. **Configure environment:**
   ```bash
   DHAN_CLIENT_ID=your_id
   DHAN_ACCESS_TOKEN=your_token
   LIVE=1  # Enable live mode
   ```

3. **Verify broker adapter:**
   - Check `src/pdp/orders/broker.py` for Dhan SDK usage
   - All orders are validated against Dhan's rules (margin, liquidity, hours)

---

## Testing

### Unit Tests

```bash
# Run all tests
uv run pytest

# Run a specific module
uv run pytest tests/orders/ -v

# Run with output
uv run pytest -s tests/positional/test_aggregation.py
```

### Integration Tests

Tests hitting real PostgreSQL/MongoDB/Redis (via Docker):

```bash
# Make sure docker-compose is running
docker compose ps

# Run integration tests
uv run pytest tests/ -m integration
```

### Frontend Testing

```bash
cd frontend

# Run unit tests
npm test

# Run e2e tests with Playwright
npm run test:e2e

# Debug e2e tests in headed mode
npm run test:e2e -- --headed
```

---

## Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker compose logs postgres

# Reset database (WARNING: deletes all data)
docker compose down -v postgres
docker compose up -d postgres
uv run alembic upgrade head
```

### Redis Connection Issues

```bash
# Check Redis is running and responsive
docker compose exec redis redis-cli ping
# Should return: PONG
```

### MongoDB Connection Issues

```bash
# Check MongoDB is running
docker compose logs mongo

# Connect and check collections
docker compose exec mongo mongosh --eval "show dbs"
```

### API Server Won't Start

```bash
# Check logs
docker compose logs -f

# Verify Python dependencies
uv sync

# Verify migrations applied
uv run alembic current

# Try manual server with full traceback
uv run python -c "from pdp.main import app; print(app)"
```

### Type Checking Errors

```bash
# Full pyright output with context
uv run pyright --outputjson | jq .

# Check specific file
uv run pyright src/pdp/orders/broker.py --verbose
```

---

## Frontend Development

### Setup

```bash
cd frontend
npm install
npm run dev
```

### Building for Production

```bash
npm run build
# Output in frontend/dist/
```

### Component Library

We use **shadcn/ui** for components. Add a component:

```bash
npm run add -- button  # adds Button component
```

---

## Contributing

1. **Start with a spec proposal:**
   ```bash
   npx -y @fission-ai/openspec new my-feature
   ```

2. **Implement in a branch:**
   ```bash
   git checkout -b feat/my-feature
   ```

3. **Follow conventions:**
   - One mutation per API endpoint
   - Type check: `uv run pyright`
   - Lint: `uv run ruff check --fix`
   - Test: `uv run pytest`

4. **Archive when done:**
   ```bash
   npx -y @fission-ai/openspec archive my-feature
   ```

5. **Create a PR** linking to the archived spec.

---

## Resources

- 📋 **Architecture & Tech Stack**: [openspec/project.md](openspec/project.md)
- 🤖 **Agent Guidance**: [CLAUDE.md](CLAUDE.md) (for Claude Code / LLM integration)
- 📚 **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs) (when running)
- 🌐 **Dhan SDK**: [dhanhq on PyPI](https://pypi.org/project/dhanhq/)
- 🗺️ **OpenSpec**: [@fission-ai/openspec](https://github.com/fission-ai/openspec)

---

## Status

| Capability                   | Status | Notes |
|------------------------------|--------|-------|
| **add-platform-skeleton**    | ✅ Spec | FastAPI + async DB setup |
| **add-instrument-registry**  | ✅ Spec | NSE/BSE/MCX instruments |
| **add-market-data-feed**     | ✅ Spec | Dhan WebSocket adapter |
| **add-paper-broker**         | ✅ Spec | Paper trading engine |
| **add-portfolio-engine**     | 🟡 Stub | Holdings + P&L tracking |
| **add-intraday-monitor**     | 🟡 Stub | Algo + manual trading UI |
| **add-positional-monitor**   | 🟡 WIP | Greeks + expiry awareness |
| **add-strategy-host**        | ✅ Spec | Pluggable strategy engine |
| **add-backtest-engine**      | 🟡 Stub | Historical backtesting |
| **add-options-analytics**    | 🟡 Stub | IV / Greeks visualization |
| **add-alerts-engine**        | 🟡 Stub | Price / Greeks alerts |
| **add-frontend-skeleton**    | 🟡 WIP | Vite + React + TanStack |

Legend: ✅ Spec finalized | 🟡 In progress | 🟢 Live
