## MODIFIED Requirements

### Requirement: Event persistence and history endpoint

The system SHALL persist every emitted event to the MongoDB `events` collection with a TTL of `EVENTS_TTL_DAYS` (default 14) and SHALL expose `GET /api/v1/events` returning recent events newest-first, filterable by `security_id`, `event_type`, and `severity`, with a `limit` (default 100) and an `offset` (default 0) for pagination. The store's `list_events()` MUST accept the `offset` keyword the route always supplies — omitting it is non-conforming, since the default `offset=0` from pagination means every call, not only an explicitly-paginated one, would fail.

#### Scenario: Event persisted and retrievable
- **WHEN** a `PSAR_FLIP` event is emitted and `GET /api/v1/events?event_type=PSAR_FLIP` is called
- **THEN** the response includes that event with its title, message, payload, and UTC timestamp

#### Scenario: Default pagination does not 500
- **WHEN** `GET /api/v1/events` is called with no query parameters
- **THEN** the response is HTTP 200 (`PaginationParams` supplies `limit=50, offset=0`, and the store accepts both)

#### Scenario: Explicit offset pages past the first N events
- **WHEN** `GET /api/v1/events?offset=20&limit=10` is called
- **THEN** the response is HTTP 200 and returns the next 10 events after skipping the first 20 (newest-first order preserved)
