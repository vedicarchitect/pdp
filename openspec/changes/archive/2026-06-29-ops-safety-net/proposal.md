## Why

Three operational-hygiene gaps make incidents harder to handle than they should be:

1. **No global exception handler.** FastAPI routes shape their own errors; an unhandled exception
   bubbles up as a default 500 that can leak internals and is logged inconsistently.
2. **Secrets in logs.** `app_starting` logs `DHAN_*` and there is no redaction in the structlog
   pipeline, so access tokens / JWTs can land in plaintext (and ship to OpenSearch).
3. **A stalled feed cannot halt trading.** The `market-feed-resilience` change emits `feed_stale`,
   but nothing consumes it to pause live entries.

OpenAlgo's reference platform addresses the first two with a single error sink (`errors.jsonl`,
"read this first") and a `SensitiveDataFilter` applied to every log handler. This change ports
those and wires the feed-stale signal into the existing kill-switch.

## What Changes

- **Global exception handler** — one `@app.exception_handler` in `main.py` returning a
  standardized JSON error shape and logging the traceback exactly once.
- **`errors.jsonl` sink** — an ERROR-only structlog sink writing one JSON object per line
  (timestamp, logger, file:line, message, traceback, request method/path), truncated on startup.
- **Sensitive-data redaction** — a `SensitiveDataFilter` structlog processor (access token / api
  key / password / bearer / `eyJ…` JWT) inserted **before** the JSON renderer and the OpenSearch
  sink so redaction covers every sink.
- **Feed-stale → safe-halt** — when `feed_stale` persists beyond `FEED_STALE_HALT_SECONDS`, notify
  `KillSwitchService` to pause new live entries (a new trigger source on the existing kill-switch).
  Paper is unaffected.

## Capabilities

### New Capabilities
- `ops-safety`: standardized exception handling, a durable structured error sink, secret redaction
  across all log sinks, and a feed-stale-driven safe-halt that reuses the kill-switch.

### Modified Capabilities
_(none — `platform-core` and the observability pipeline are extended via new processors/handlers,
not altered)_

## Impact

- **`backend/pdp/main.py`**: register the global exception handler; truncate `errors.jsonl` on
  startup.
- **`backend/pdp/logging.py`**: add `SensitiveDataFilter` and the `errors.jsonl` sink as structlog
  processors, ordered before `JSONRenderer` and the existing `opensearch_sink`.
- **`backend/pdp/risk/`**: new `feed_stale` trigger source on `KillSwitchService` (pause live
  entries; paper exempt).
- **`backend/pdp/settings.py`**: `ERRORS_JSONL_PATH` (default `logs/errors.jsonl`),
  `ERRORS_JSONL_MAX_LINES` (default 1000), `FEED_STALE_HALT_SECONDS` (default 180),
  `LOG_REDACTION_ENABLED` (default True).
- **`docs/RUNBOOK.md`**: error-sink + redaction + safe-halt operating notes.

**Depends on:** `market-feed-resilience` for the `feed_stale` event (item 4 only).
