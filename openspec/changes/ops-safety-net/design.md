## Context

`pdp/logging.py` configures structlog with an ordered processor chain ending in
`opensearch_sink` (Tier-A shipper, before JSON so it sees the structured dict) then
`JSONRenderer()`. `RequestIdMiddleware` binds `request_id`/`source`. There is no redaction and no
dedicated error file; `main.py:app_starting` logs `DHAN_*` values directly.

`pdp/main.py` has a FastAPI app factory with lifespan wiring and `/healthz` + `/readyz`, but no
`@app.exception_handler`. `pdp/risk/KillSwitchService` already supports a hard-cap auto-kill; it is
the natural consumer of a sustained `feed_stale` signal.

OpenAlgo reference: `SensitiveDataFilter` (regex redaction applied to *all* handlers, file and JSON
both), `JSONErrorFormatter` → `errors.jsonl` truncated on boot ("Claude reads this file first").

## Goals / Non-Goals

**Goals:**
- One place that turns any unhandled exception into a standardized JSON body + a single log line.
- A durable, machine-readable ERROR sink (`errors.jsonl`) that is fast to scan during an incident.
- No secret-shaped substring reaches any sink (console, file, OpenSearch).
- A sustained feed-stall pauses *new live entries* without touching paper or open positions.

**Non-Goals:**
- Replacing the OpenSearch pipeline — redaction sits in front of it, errors.jsonl is additive.
- A full resource monitor (FD/mem/threads) — included only as an optional stretch task on
  `/readyz`, not a hard requirement.
- Auto-resuming after a halt — resume stays a deliberate operator/kill-switch action.

## Decisions

### D1 — Redaction is a processor, placed before JSON and OpenSearch
`SensitiveDataFilter` runs as a structlog processor inserted ahead of both `opensearch_sink` and
`JSONRenderer`, so a single implementation covers every downstream sink. Patterns: `access[_-]?token`,
`api[_-]?key`, `password`, `bearer <…>`, and `eyJ[\w.\-]{20,}` (JWT). Redacts to `***`.

### D2 — errors.jsonl is an additive ERROR-only sink, truncated on startup
A processor (or dedicated handler) writes one JSON object per ERROR record and is a no-op for
lower levels. On startup `main.py` truncates the file to `ERRORS_JSONL_MAX_LINES`. It does not
replace the main log or OpenSearch — it is the fast local incident view.

### D3 — Global handler returns a stable shape, logs once
`@app.exception_handler(Exception)` returns `{"error": {"type", "message", "request_id"}}` with a
500 (and lets `HTTPException` keep its own status). It logs the traceback once at ERROR (which then
also lands in errors.jsonl via D2). Existing per-route `HTTPException` usage is unchanged.

### D4 — Safe-halt reuses the kill-switch, live-only
A small subscriber to `feed_stale` starts a timer; if staleness persists past
`FEED_STALE_HALT_SECONDS`, it calls `KillSwitchService` with a `feed_stale` reason to pause new
live entries. Paper orders and existing positions are unaffected; clearing the stall does not
auto-resume (operator action, consistent with the existing kill-switch).

## Failure Modes

- **Redaction regex misses a novel secret format** → defence-in-depth only; the primary control
  remains not logging raw creds. New patterns are cheap to add.
- **errors.jsonl write failure (disk full)** → swallowed and warned; never breaks request handling.
- **Halt fires on a brief blip** → `FEED_STALE_HALT_SECONDS` (180s default) is well above the
  watchdog's reconnect window, so a normal reconnect clears it before a halt.

## Open Questions

- Whether the optional `/readyz` resource snapshot is worth the `psutil` dependency now or deferred
  to `cloud-deploy-aws` — left as a stretch task.
