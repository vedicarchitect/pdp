# platform-core Specification

## Purpose
TBD - created by archiving change add-platform-skeleton. Update Purpose after archive.
## Requirements
### Requirement: Application boot

The system SHALL expose a runnable ASGI application via `uv run pdp` (or `uvicorn pdp.main:app`) that starts uvicorn with the `uvloop` event loop and `httptools` HTTP parser.

#### Scenario: Healthz returns OK on boot

- **WHEN** the app is started and `GET /healthz` is requested
- **THEN** the response is HTTP 200 with JSON body `{"status": "ok", "app": "pdp", "git_sha": "<sha>", "started_at": "<iso8601>"}`

#### Scenario: Readyz checks DB and Mongo

- **WHEN** the database, Redis, and MongoDB are all reachable and `GET /readyz` is requested
- **THEN** the response is HTTP 200 with `{"status": "ready", "db": "ok", "redis": "ok", "mongo": "ok"}`
- **AND WHEN** any one of the database, Redis, or MongoDB is unreachable
- **THEN** the response is HTTP 503 with the corresponding field set to `"error"` while `/healthz` continues to return 200

### Requirement: Settings via environment

The system SHALL load configuration via `pydantic-settings` from a `.env` file at repo root, supporting at minimum `DATABASE_URL`, `REDIS_URL`, `LOG_LEVEL`, `LIVE`, `APP_NAME`, `GIT_SHA`, `ENV`. The `LIVE` flag SHALL default to `false`.

#### Scenario: Missing required setting fails loudly

- **WHEN** `Settings()` is constructed without `DATABASE_URL` in env or `.env`
- **THEN** a `ValidationError` is raised at boot listing the missing field

#### Scenario: LIVE defaults to false

- **WHEN** `LIVE` is not set in the environment
- **THEN** `Settings().LIVE` is `False` and any module reading `settings.LIVE` treats orders as paper

### Requirement: Structured logging

The system SHALL emit JSON-formatted log lines to stdout via `structlog`, with every HTTP request bound to a `request_id` propagated through downstream log calls.

#### Scenario: Request gets a request_id

- **WHEN** any HTTP request is handled
- **THEN** all log entries emitted during that request include a `request_id` field generated as a UUIDv4 (or honored from `X-Request-ID` header if provided)

#### Scenario: Logs are JSON

- **WHEN** the app logs at any level
- **THEN** the line written to stdout is valid JSON with at minimum `event`, `level`, `timestamp` fields

### Requirement: Async DB session

The system SHALL provide an async SQLAlchemy 2.0 engine and an `async_session_maker`, plus a FastAPI dependency `get_db` that yields an `AsyncSession`. Alembic SHALL be configured with a baseline (empty) migration so future changes can `alembic revision --autogenerate`.

#### Scenario: Session is closed after request

- **WHEN** a route depending on `get_db` finishes (success or exception)
- **THEN** the underlying `AsyncSession` is closed and the connection returned to the pool

#### Scenario: Alembic baseline runs

- **WHEN** `alembic upgrade head` is run against a fresh database
- **THEN** the migration completes successfully and the `alembic_version` table exists

