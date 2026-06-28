# trade-analysis-feedback-loop Specification

## Purpose
TBD - created by archiving change trade-analysis-feedback-loop. Update Purpose after archive.
## Requirements
### Requirement: OpenSearch client and settings
The system SHALL provide an env-configured async OpenSearch client accessed through a
singleton, controlled by an `OPENSEARCH_ENABLED` flag and `OPENSEARCH_*` settings read via
`get_settings()`, so the pipeline can be turned off and pointed at any cluster (local or AWS)
without code changes.

#### Scenario: Client disabled by default
- **WHEN** `OPENSEARCH_ENABLED` is `false`
- **THEN** `get_opensearch()` returns `None` and the pipeline is inert (no connection
  attempts, no errors)

#### Scenario: Client configured from settings
- **WHEN** `OPENSEARCH_ENABLED` is `true` and `OPENSEARCH_URL` is set
- **THEN** `get_opensearch()` returns a connected async client using `OPENSEARCH_URL`,
  optional `OPENSEARCH_USER`/`OPENSEARCH_PASSWORD`, and `OPENSEARCH_VERIFY_CERTS`

### Requirement: Index templates and mappings
The system SHALL register composable index templates for the universal log index
(`pdp-logs-*`) and the typed analytics indices (`pdp-strangle-events-*`, `pdp-trades-*`,
`pdp-journal-*`, `pdp-backtest-runs-*`, `pdp-backtest-days-*`, `pdp-backtest-trades-*`) with
`dynamic: false` and explicit field types, via an idempotent `ensure_templates()` run at
application startup.

#### Scenario: Templates applied at startup
- **WHEN** the application starts with OpenSearch enabled
- **THEN** `ensure_templates()` creates or updates each index template and is safe to run
  repeatedly without error

#### Scenario: Strict mapping ignores unknown fields
- **WHEN** a typed document carries a field not present in its template mapping
- **THEN** the unknown field is ignored (not indexed) rather than altering the mapping

### Requirement: Non-blocking indexer
The system SHALL ship all documents through a single `OpenSearchIndexer` that enqueues
documents without blocking and flushes them in bulk on a background loop, so logging and
trading code paths never await I/O.

#### Scenario: Enqueue never blocks
- **WHEN** `enqueue(index, doc)` is called
- **THEN** it returns immediately without awaiting, and when the queue is full the document
  is dropped and a drop counter is incremented (the caller is never blocked)

#### Scenario: OpenSearch unavailable does not break the app
- **WHEN** OpenSearch is unreachable during a flush
- **THEN** the indexer logs a single warning, discards the batch, and the API and stdout
  logging continue unaffected

#### Scenario: Bulk flush on interval or batch size
- **WHEN** queued documents reach `OPENSEARCH_BULK_MAX` or `OPENSEARCH_BULK_INTERVAL`
  elapses
- **THEN** the indexer flushes the pending documents in a single bulk request

### Requirement: Universal log shipping with source segregation
The system SHALL ship every backend `structlog` record at or above `OPENSEARCH_LOG_LEVEL` to
`pdp-logs-*` through a structlog processor, carrying `@timestamp`, `source`, `level`,
`logger`, `event`, `request_id`, and remaining bound context, so all backend logs are
searchable in one place segregated by `source`.

#### Scenario: Every log record is shipped
- **WHEN** any backend module emits a log at or above the configured level
- **THEN** a corresponding document is enqueued to `pdp-logs-*` and the original log still
  renders to stdout unchanged

#### Scenario: Source is derived and overridable
- **WHEN** a log record has no explicit `source` bound
- **THEN** `source` is derived from the logger/module; **and WHEN** a caller binds
  `source` via context, that value is used instead

#### Scenario: Observability logger does not feed itself
- **WHEN** the observability module's own logger emits a record (e.g. a flush warning)
- **THEN** that record is not shipped to OpenSearch (no feedback loop)

### Requirement: Typed analytics sinks
The system SHALL route high-value events to typed indices via pure mapper functions, dual-sinking
alongside their existing durable writes: strangle events (from `StrategyDailyLog`), fills and
daily journal rollups (from `JournalService`), and backtest run/day/trade documents (from
`BacktestStore`), with idempotent document ids.

#### Scenario: Strangle event dual-sinks
- **WHEN** `DirectionalStrangle` writes a canonical event to its JSONL log
- **THEN** the same event is also enqueued to `pdp-strangle-events-*` with a deterministic
  id, and the JSONL write is unchanged

#### Scenario: Journal and backtest events sink
- **WHEN** `JournalService` flushes a day or `BacktestStore` upserts a run
- **THEN** the corresponding `pdp-trades-*`/`pdp-journal-*` or `pdp-backtest-*` documents are
  enqueued, while the Mongo write remains the source of truth

### Requirement: UI log ingest endpoint
The system SHALL expose `POST /api/v1/logs/ingest` that accepts a batch of UI/external log
records and feeds them into the same pipeline with `source=ui`, so Flutter app logs land in
`pdp-logs-*` alongside backend logs.

#### Scenario: UI batch is ingested
- **WHEN** a valid batch of records is POSTed to `/api/v1/logs/ingest`
- **THEN** each record is enqueued to `pdp-logs-*` with `source=ui` plus `screen`, `level`,
  `build`, and `device` fields, and the endpoint returns the accepted count

#### Scenario: Invalid batch is rejected
- **WHEN** a malformed batch is POSTed
- **THEN** the endpoint returns a 422 without enqueuing any document

### Requirement: Log search and session-narrative API
The system SHALL expose REST endpoints to search the unified logs and to return a
bar-anchored strangle session narrative for a date, built by querying
`pdp-strangle-events-*`, so operators and Claude can review a day's decisions without manual
file export.

#### Scenario: Session narrative returned for a date
- **WHEN** `GET /api/v1/analysis/session?date=YYYY-MM-DD` is called and events exist for that
  date
- **THEN** the response groups events into bars (each anchored by a `bias_evaluated` event)
  with the bucket, score, spot, bias votes, leg status, and subsequent actions per bar

#### Scenario: No events yields 404
- **WHEN** `GET /api/v1/analysis/session?date=YYYY-MM-DD` is called and no events exist for
  that date
- **THEN** the endpoint returns 404

### Requirement: Dashboards as code
The system SHALL store OpenSearch Dashboards saved objects as versioned NDJSON under
`infra/opensearch/dashboards/` and provide a task that imports them idempotently, so the
dashboard set is reproducible across environments.

#### Scenario: Dashboards imported by task
- **WHEN** `task search:init` runs against a reachable OpenSearch Dashboards
- **THEN** the saved-object NDJSON files are imported and re-running the task does not
  duplicate objects

### Requirement: Claude review prompt template
The system SHALL provide `scripts/analysis/strangle_review_prompt.md` — a prompt template
that instructs Claude to review a session narrative (identify the most consequential
decisions, assess whether the bias bucket was predictive, and suggest parameter
adjustments).

#### Scenario: Prompt template exists
- **WHEN** an operator wants Claude to review a session
- **THEN** `scripts/analysis/strangle_review_prompt.md` exists and references the
  session-narrative output as its input

