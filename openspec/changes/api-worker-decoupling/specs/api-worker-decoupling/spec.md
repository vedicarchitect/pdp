## ADDED Requirements

### Requirement: Composable startup groups

The application lifespan SHALL be decomposed into independently start/stoppable subsystem groups
(`infra`, `web`, `feed_engine`, `ops`, `job_runner`), each with `async start()`/`async stop()`,
and each group's startup SHALL be wrapped so a failure in one group degrades only that group and
does not crash the process or prevent other groups from starting.

#### Scenario: One group's failure does not crash the process

- **WHEN** the `feed_engine` group fails to start (e.g. Dhan connectivity error)
- **THEN** the process stays up, the failure is logged/surfaced, and the other started groups keep running

#### Scenario: Clean shutdown stops started groups in reverse

- **WHEN** the process receives a shutdown signal
- **THEN** every started group's `stop()` runs and releases its resources (no leaked connections)

### Requirement: Separately-launchable processes

The system SHALL provide three launchable entrypoints on one image — `pdp-api` (infra+web),
`pdp-engine` (infra+feed_engine), `pdp-ops` (infra+ops+job_runner) — so the stateless API, the
stateful market/strategy engine, and the background/ops workers run as independent processes. The
API SHALL boot without any Dhan/market-feed dependency.

#### Scenario: API boots without the engine

- **WHEN** `pdp-api` starts with no Dhan credentials and no engine running
- **THEN** `/healthz` is green, `/docs` is served, and read endpoints respond from PostgreSQL/Redis snapshots

#### Scenario: Engine is the only market-feed process

- **WHEN** `pdp-engine` starts
- **THEN** it holds the single Dhan feed connection and publishes ticks/bars to Redis for the API to consume

### Requirement: Redis→WebSocket bridge in the API

The API SHALL fan out live market data to `/ws/market` clients by subscribing to the engine's
Redis channels/streams (`tick.<sid>` pub/sub, `bars.<sid>.<tf>` stream) and calling the existing
`WSHub` publish methods, rather than by an in-process call from the tick router. The WS endpoints
SHALL remain served by the API.

#### Scenario: Ticks flow from engine to browser via Redis

- **WHEN** the engine publishes `tick.<sid>` and a browser is subscribed on `/ws/market`
- **THEN** the API's bridge delivers the tick to that client without the engine and API sharing a process

### Requirement: Centralized order execution via a durable command channel

Live order placement SHALL be centralized in the engine. The API SHALL validate a manual order
and enqueue it on a Redis Stream consumed by an engine consumer group; the engine SHALL run the
single margin + kill-switch gate, place to the broker, and write an ack/result back. An
idempotency key SHALL ensure an order command is processed at most once even if the engine
restarts mid-flight. The kill-switch SHALL be a high-priority command on the same channel so the
engine is the single square-off authority.

#### Scenario: Manual order is executed by the engine

- **WHEN** the API receives a valid authenticated order and enqueues it
- **THEN** the engine consumes it, places it once, and the API receives the ack/result

#### Scenario: Engine restart does not double-process a command

- **WHEN** the engine restarts after reading but before acking an order command
- **THEN** the command is re-read by the consumer group and the idempotency key prevents a second broker placement

#### Scenario: Order rejected when engine is unavailable

- **WHEN** a manual order is placed while no engine is consuming the stream
- **THEN** the API returns `503` rather than silently dropping the order

### Requirement: Engine-published state snapshots

The engine SHALL publish the state the API previously read from in-process objects: indicator
snapshots (`indicators:<sid>:<tf>`, updated on bar close) and live position/MTM
(`position:<...>`), so the API can serve indicator and live-MTM reads without holding the
`IndicatorEngine`/`PortfolioService` in-process. Durable positions and orders SHALL continue to be
read from PostgreSQL.

#### Scenario: API serves indicator values from the snapshot

- **WHEN** the execution console requests indicator values
- **THEN** the API reads them from the `indicators:<sid>:<tf>` Redis snapshot published by the engine

### Requirement: Per-process readiness and graceful degradation

Each process SHALL expose a `/readyz` that reflects only the subsystem groups it runs. When the
engine is unavailable, the API SHALL degrade gracefully: serve last-known snapshots with a
"feed offline" indication and return `503` for actions that require the engine (e.g. manual
orders), rather than crashing or hanging.

#### Scenario: API degrades when the engine is down

- **WHEN** the engine is not running
- **THEN** the API's read endpoints return last-known snapshot data flagged stale, and engine-dependent actions return `503`

#### Scenario: Readiness reflects only local groups

- **WHEN** `pdp-api`'s `/readyz` is polled
- **THEN** it reports on infra+web only, not on the engine's feed groups

### Requirement: Per-process connection pool budgeting

Each process SHALL size its PostgreSQL and MongoDB connection pools so the combined footprint of
all processes stays within the database's connection limits, tunable via settings.

#### Scenario: Combined pools stay within the Postgres limit

- **WHEN** `pdp-api`, `pdp-engine`, and `pdp-ops` all run
- **THEN** their combined configured PostgreSQL pool sizes do not exceed the server's `max_connections`
