# mongo-store Specification

## Purpose
MongoDB client lifecycle, collection initialisation, and connection settings for the PDP platform. Provides `app.state.mongo_client` and `app.state.mongo_db` to all application components, and ensures the `market_bars` (time-series) and `option_chains` (TTL) collections exist on startup without manual migration.

## Requirements

### Requirement: MongoDB client lifecycle
The system SHALL connect a `motor.AsyncIOMotorClient` on application startup using `settings.MONGO_URI` and disconnect it gracefully on shutdown. The client SHALL be stored on `app.state.mongo_client` and the target database on `app.state.mongo_db`.

#### Scenario: Client connects on startup
- **WHEN** the FastAPI application lifespan starts
- **THEN** `app.state.mongo_client` is a live `AsyncIOMotorClient` and `app.state.mongo_db` references the database named by `settings.MONGO_DB_NAME`

#### Scenario: Client disconnects on shutdown
- **WHEN** the FastAPI application lifespan exits (normal or on SIGTERM)
- **THEN** `app.state.mongo_client.close()` is called and no motor background threads remain

### Requirement: Collection initialisation
The system SHALL create the `market_bars` and `option_chains` collections idempotently on startup, including all required indexes, so no manual migration step is needed.

#### Scenario: market_bars created as time-series collection
- **WHEN** the app starts and `market_bars` does not yet exist
- **THEN** a MongoDB native time-series collection is created with `timeField="ts"`, `metaField="metadata"`, and `granularity="seconds"`

#### Scenario: market_bars creation is idempotent
- **WHEN** the app starts and `market_bars` already exists
- **THEN** no error is raised and the collection is left unchanged

#### Scenario: option_chains created with TTL index
- **WHEN** the app starts and `option_chains` does not yet exist
- **THEN** a standard collection is created and a TTL index is applied on `captured_at` with `expireAfterSeconds` equal to `settings.MONGO_CHAIN_TTL_DAYS * 86400`

#### Scenario: option_chains TTL index is idempotent
- **WHEN** the app starts and `option_chains` and its TTL index already exist
- **THEN** no error is raised

### Requirement: MongoDB settings
The system SHALL read MongoDB connection configuration from environment variables with safe defaults for local development.

#### Scenario: Default URI targets localhost
- **WHEN** `MONGO_URI` is not set in the environment
- **THEN** `settings.MONGO_URI` defaults to `"mongodb://localhost:27017"`

#### Scenario: Default database name
- **WHEN** `MONGO_DB_NAME` is not set in the environment
- **THEN** `settings.MONGO_DB_NAME` defaults to `"pdp"`

#### Scenario: Default chain TTL
- **WHEN** `MONGO_CHAIN_TTL_DAYS` is not set in the environment
- **THEN** `settings.MONGO_CHAIN_TTL_DAYS` defaults to `30`
