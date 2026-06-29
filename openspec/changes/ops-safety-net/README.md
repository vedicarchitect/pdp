# ops-safety-net

**Minimal context set** (load only these when working this chunk):
- backend/pdp/logging.py, backend/pdp/main.py
- backend/pdp/risk/ (KillSwitchService), backend/pdp/settings.py
- backend/pdp/observability/ (existing opensearch_sink ordering)
- depends on: market-feed-resilience (feed_stale event)
- reference: openalgo SensitiveDataFilter + JSONErrorFormatter (errors.jsonl)
