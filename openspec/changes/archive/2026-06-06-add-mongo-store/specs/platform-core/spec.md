## MODIFIED Requirements

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
