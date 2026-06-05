# PDP — OpenSpec-Driven Trading & Investment Platform

Self-hosted, paper-first trading & investment platform for intraday, positional, and portfolio management. Every capability is defined as an OpenSpec proposal before implementation.

## Quickstart

```bash
# 1. Copy env
cp .env.example .env

# 2. Bring up infra
docker compose up -d timescale redis

# 3. Install Python deps
uv sync

# 4. Apply DB migrations
uv run alembic upgrade head

# 5. Run the API
uv run uvicorn pdp.main:app --reload
# → http://localhost:8000/healthz
```

## OpenSpec

```bash
# List active change proposals
npx -y @fission-ai/openspec list

# Validate all
npx -y @fission-ai/openspec validate --all --strict

# Show a change
npx -y @fission-ai/openspec show add-platform-skeleton
```

See [openspec/project.md](openspec/project.md) for the full project profile and [CLAUDE.md](CLAUDE.md) for agent guidance.

## Layout

```
PDP/
├── openspec/          OpenSpec specs & in-flight changes
├── src/pdp/           Python package
├── alembic/           DB migrations
├── tests/             pytest suite
├── docker-compose.yml TimescaleDB + Redis (dev)
└── Taskfile.yml       task runner
```

## Status

| Change                       | Status |
|------------------------------|--------|
| add-platform-skeleton        | spec ✓ — implementation in progress |
| add-instrument-registry      | spec ✓ |
| add-market-data-feed         | spec ✓ |
| add-paper-broker             | spec ✓ |
| add-portfolio-engine         | stub |
| add-intraday-monitor         | stub |
| add-positional-monitor       | stub |
| add-strategy-host            | stub |
| add-backtest-engine          | stub |
| add-options-analytics        | stub |
| add-alerts-engine            | stub |
| add-frontend-skeleton        | stub |
