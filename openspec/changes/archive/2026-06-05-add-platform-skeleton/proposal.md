## Why

PDP is a greenfield repo; every other capability proposal (market feed, paper broker, portfolio engine, etc.) needs a runnable FastAPI shell, async DB session, structured logging, and a paper-default config gate to land against. This change establishes that foundation.

## What Changes

- New `pdp` Python package (`src/pdp/`) with FastAPI app factory, lifespan, `/healthz`.
- `pydantic-settings`-driven `Settings` loaded from `.env`; `LIVE` defaults to `false`.
- `structlog` JSON logging + `request_id` middleware.
- Async SQLAlchemy 2.0 engine, `async_session_maker`, `get_db` dependency, alembic baseline.
- `docker-compose.yml` for TimescaleDB + Redis (dev).
- `Taskfile.yml` for `task dev`, `task test`, `task openspec:validate`.
- Baseline pytest suite (`test_healthz`, `test_settings_loads`).

## Capabilities

### New Capabilities

- `platform-core`: Application boot, configuration, logging, health, and DB session — the substrate every other capability depends on.

### Modified Capabilities

(none — greenfield)

## Impact

- Creates the entire `src/pdp/` tree, `pyproject.toml`, `alembic/`, `docker-compose.yml`, `Taskfile.yml`, `.env.example`.
- Introduces deps: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `structlog`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `msgspec`, `polars`, `redis`, `httpx`.
- No live broker calls; no market data flow yet.
