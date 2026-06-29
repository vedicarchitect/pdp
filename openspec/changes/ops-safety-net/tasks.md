## 1. Settings

- [ ] 1.1 Add to `pdp/settings.py`: `ERRORS_JSONL_PATH` (str, default "logs/errors.jsonl"),
  `ERRORS_JSONL_MAX_LINES` (int, default 1000), `LOG_REDACTION_ENABLED` (bool, default True),
  `FEED_STALE_HALT_SECONDS` (int, default 180)

## 2. Sensitive-data redaction

- [ ] 2.1 Add a `SensitiveDataFilter` structlog processor in `pdp/logging.py` (regex:
  access[_-]?token, api[_-]?key, password, bearer, `eyJ[\w.\-]{20,}` JWT → `***`)
- [ ] 2.2 Insert it BEFORE `opensearch_sink` and `JSONRenderer` so all sinks are covered
- [ ] 2.3 Gate on `LOG_REDACTION_ENABLED`; verify the `app_starting` banner redacts `DHAN_*`

## 3. errors.jsonl sink

- [ ] 3.1 Add an ERROR-only processor/handler in `pdp/logging.py` writing one JSON line
  (timestamp, logger, file:line, message, traceback, request method/path) to `ERRORS_JSONL_PATH`
- [ ] 3.2 No-op for levels below ERROR
- [ ] 3.3 Truncate the file to `ERRORS_JSONL_MAX_LINES` on startup in `pdp/main.py`
- [ ] 3.4 Swallow+warn on write failure (never break request handling)

## 4. Global exception handler

- [ ] 4.1 Register `@app.exception_handler(Exception)` in `pdp/main.py` returning
  `{"error": {"type","message","request_id"}}` at HTTP 500; log traceback once at ERROR
- [ ] 4.2 Leave `HTTPException` handling intact (status/detail preserved)

## 5. Feed-stale safe-halt

- [ ] 5.1 Subscribe to the `feed_stale` event (from `market-feed-resilience`); start a timer
- [ ] 5.2 If staleness persists past `FEED_STALE_HALT_SECONDS`, engage `KillSwitchService` with a
  `feed_stale` reason (new trigger source in `pdp/risk/`)
- [ ] 5.3 Ensure paper orders and existing positions are unaffected; no auto-resume on recovery

## 6. Validation + archive

- [ ] 6.1 `task openspec:validate -- ops-safety-net --strict` passes
- [ ] 6.2 `task test` green for redaction + error-sink + exception-handler unit tests
- [ ] 6.3 `docs/RUNBOOK.md` — error-sink, redaction, and safe-halt operating notes
- [ ] 6.4 Owner check: raise a test exception → standard JSON + one errors.jsonl line, no secrets
  present in any sink

## 7. Stretch (optional)

- [ ] 7.1 Add a lightweight FD/memory/thread snapshot to `/readyz` (psutil) — defer to
  `cloud-deploy-aws` if the dependency is unwanted now
