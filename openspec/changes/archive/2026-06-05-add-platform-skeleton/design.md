# Design — add-platform-skeleton

## Goals

Provide a minimal, observable, paper-default FastAPI shell that future capability changes can attach to without rework.

## Architecture

```
uvicorn (uvloop + httptools)
  └── FastAPI app (factory pattern, lifespan-managed resources)
        ├── middleware: request_id, structlog binding
        ├── /healthz, /readyz
        └── DI: get_db() → AsyncSession (SQLAlchemy 2.0 + asyncpg)

Settings (pydantic-settings, .env)
  ├── LIVE: bool = False                # paper-mode gate
  ├── DATABASE_URL: PostgresDsn
  ├── REDIS_URL: RedisDsn
  ├── LOG_LEVEL: str = "INFO"
  └── APP_NAME, GIT_SHA, ENV

structlog (JSON renderer)
  └── stdlib logging adapter so SQLAlchemy/uvicorn logs flow through it
```

## Key Decisions

- **Single uvicorn worker** in v1: hot path is single-process so Redis pub/sub fan-out is in-memory. Horizontal scale comes later via Redis stream consumer groups.
- **Alembic against async engine**: use `compare_type=True` + sync URL in `env.py` (asyncpg → psycopg URL for migrations).
- **`msgspec.Struct` for responses, `pydantic` for request validation only**: msgspec is ~10× faster on serialization, which matters for the upcoming market-data WS endpoints.
- **`LIVE=false` default**: every order-execution change reads this gate; switching to live requires explicit env override.

## Failure Modes

- Missing `.env` → `Settings()` raises clear `ValidationError` listing missing fields (don't silently default DB URL).
- DB unreachable on boot → `/healthz` still returns 200 (process health); `/readyz` returns 503 (dependency health). This split is intentional so Docker/K8s liveness probes don't kill the app during transient outages.

## Open Questions

(none for skeleton; deferred to dependent changes)
