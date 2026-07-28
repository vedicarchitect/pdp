## ADDED Requirements

### Requirement: Bounded startup when OpenSearch is unreachable

The system SHALL NOT let OpenSearch template registration at boot hold back application startup
by more than a few seconds when `OPENSEARCH_ENABLED=1` and OpenSearch is unreachable. A timeout on
that one-time registration step SHALL be logged as a warning and treated as non-fatal, consistent
with the module's documented "OS down = no-op" contract for every other OpenSearch-dependent path.

#### Scenario: Startup completes quickly with OpenSearch down
- **WHEN** the API boots with `OPENSEARCH_ENABLED=1` and OpenSearch is not reachable at
  `OPENSEARCH_URL`
- **THEN** `Application startup complete` is reached within a few seconds, not tens of seconds of
  per-template connection retries

#### Scenario: The API serves requests immediately after startup
- **WHEN** OpenSearch is down during boot
- **THEN** the first HTTP request after `Application startup complete` is served normally, not
  queued behind a still-in-progress lifespan startup

#### Scenario: Template registration still succeeds when OpenSearch is up
- **WHEN** the API boots with `OPENSEARCH_ENABLED=1` and OpenSearch is reachable
- **THEN** all index templates are registered exactly as before this change, with no timeout hit
