## 1. Project Bootstrap

- [x] 1.1 Create `pyproject.toml` with `uv` (project name `pdp`, Python 3.13)
- [x] 1.2 Add deps: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `structlog`, `sqlalchemy[asyncio]`, `asyncpg`, `psycopg[binary]`, `alembic`, `msgspec`, `polars`, `redis`, `httpx`
- [x] 1.3 Add dev deps: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `pyright`, `httpx[cli]`
- [x] 1.4 Add `[project.scripts]` entry `pdp = "pdp.cli:main"`
- [x] 1.5 Write `.env.example` documenting every required setting
- [x] 1.6 Write `docker-compose.yml` (timescaledb 2 + redis 7 + pgadmin)
- [x] 1.7 Write `Taskfile.yml` with `dev`, `test`, `lint`, `typecheck`, `openspec:validate`

## 2. Core Modules

- [x] 2.1 `src/pdp/settings.py` — `Settings(BaseSettings)` with all env fields
- [x] 2.2 `src/pdp/logging.py` — structlog config + `RequestIdMiddleware`
- [x] 2.3 `src/pdp/db/session.py` — engine, `async_session_maker`, `get_db`
- [x] 2.4 `src/pdp/main.py` — app factory, lifespan (open/close engine + redis), `/healthz`, `/readyz`
- [x] 2.5 `src/pdp/cli.py` — `main()` that runs `uvicorn pdp.main:app`

## 3. Alembic Baseline

- [x] 3.1 `alembic init alembic`
- [x] 3.2 Configure `alembic/env.py` to read `DATABASE_URL` from `Settings` and use sync URL (psycopg) for migrations
- [x] 3.3 Generate empty baseline migration `0001_baseline.py`

## 4. Tests

- [x] 4.1 `tests/test_healthz.py` — `httpx.AsyncClient` calls `/healthz`, asserts 200 + shape
- [x] 4.2 `tests/test_settings.py` — Settings raises on missing `DATABASE_URL`; LIVE defaults to False
- [x] 4.3 `tests/test_logging.py` — log record includes `request_id` field _(covered by `test_request_id_header_round_trips` in test_healthz.py)_

## 5. Validation + Archive

- [x] 5.1 `openspec validate --strict add-platform-skeleton` → exits 0
- [x] 5.2 `uv sync && uv run pytest` → all baseline tests pass
- [x] 5.3 `task dev` boots, `curl localhost:8000/healthz` returns 200
- [x] 5.4 `openspec archive add-platform-skeleton` to promote `platform-core` into `openspec/specs/`
