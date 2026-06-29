## ADDED Requirements

### Requirement: Global exception handler
The system SHALL handle any unhandled exception with a single global handler that returns a
standardized JSON error body and logs the traceback exactly once.

#### Scenario: Unhandled exception returns a standard shape
- **WHEN** a route raises an exception that is not an `HTTPException`
- **THEN** the response is HTTP 500 with a body of the form
  `{"error": {"type", "message", "request_id"}}`
- **AND** the traceback is logged once at ERROR level

#### Scenario: HTTPException keeps its status
- **WHEN** a route raises an `HTTPException`
- **THEN** the configured status code and detail are preserved (not coerced to 500)

---

### Requirement: Durable structured error sink
The system SHALL write every ERROR-level log record as one JSON object per line to a dedicated
error file, truncated on startup.

#### Scenario: Error written to errors.jsonl
- **WHEN** an ERROR-level event is logged
- **THEN** a single JSON line is appended to `ERRORS_JSONL_PATH` containing timestamp, logger,
  file:line, message, traceback, and request method/path when available

#### Scenario: File truncated on startup
- **WHEN** the application starts
- **THEN** the error file is truncated to at most `ERRORS_JSONL_MAX_LINES`

#### Scenario: Lower levels are not written
- **WHEN** an INFO or WARNING event is logged
- **THEN** nothing is written to the error file

---

### Requirement: Sensitive-data redaction across all sinks
The system SHALL redact secret-shaped values from log records before they reach any sink (console,
error file, or OpenSearch).

#### Scenario: Tokens are redacted everywhere
- **WHEN** a log record contains an access token, api key, password, bearer token, or a JWT-shaped
  `eyJ…` value
- **THEN** the value is replaced with a redaction marker in every sink, including the OpenSearch
  shipper and `errors.jsonl`

#### Scenario: Startup banner does not leak credentials
- **WHEN** the application logs its startup configuration
- **THEN** `DHAN_*` credential values appear redacted, not in plaintext

---

### Requirement: Feed-stale safe-halt
The system SHALL pause new live order entries via the kill-switch when a feed-stale condition
persists beyond a configured threshold, without affecting paper trading or existing positions.

#### Scenario: Sustained stall pauses live entries
- **WHEN** a `feed_stale` condition persists for longer than `FEED_STALE_HALT_SECONDS`
- **THEN** the kill-switch is engaged with a `feed_stale` reason
- **AND** new live order entries are blocked

#### Scenario: Paper trading is unaffected
- **WHEN** the safe-halt is engaged
- **THEN** paper orders continue to be accepted

#### Scenario: Recovery does not auto-resume
- **WHEN** ticks resume after a safe-halt
- **THEN** live entries remain paused until the kill-switch is explicitly cleared
