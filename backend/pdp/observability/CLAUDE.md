# observability/ — Unified OpenSearch log pipeline

Every backend `structlog` record + Flutter UI log auto-ships to OpenSearch in realtime
through **one** non-blocking indexer, segregated by a `source` field. High-value events also
route to strict-mapped typed analytics indices. JSONL/Mongo stay the source of truth;
OpenSearch is the derived, queryable, realtime layer. Disabled unless `OPENSEARCH_ENABLED=1`.

## Files

| File | Role |
|------|------|
| `client.py` | `get_opensearch()` async singleton (returns `None` when disabled) |
| `indexer.py` | `OpenSearchIndexer` — the single sink: queue + bulk flush, non-blocking `enqueue` (drop-on-full). Module globals `set_active_indexer`/`get_active_indexer` |
| `processor.py` | `opensearch_sink` structlog processor — ships every record to `pdp-logs-*`; skips `_no_ship` logs (self) |
| `mappings.py` | Composable index templates + idempotent `ensure_templates()` |
| `sinks.py` | Pure mappers → typed docs (`strangle_event_doc`, `fill_doc`, `journal_day_doc`, `backtest_*_doc`) |
| `ingest.py` | `POST /api/v1/logs/ingest` — UI/external batch endpoint (`source=ui`) |
| `query.py` | `search_logs`, `fetch_session_events`, `build_session` (bar-anchored narrative) |
| `routes.py` | `GET /api/v1/observability/logs` + `GET /api/v1/analysis/session` |
| `init.py` | `python -m pdp.observability.init` — templates + dashboards import (`task search:init`) |
| `../../scripts/opensearch_cleanup.py` | Retention prune — deletes/trims every family except `pdp-trades-*` past a rolling window (default 7d); `task search:cleanup` |

## Indices (monthly date-suffixed, `dynamic:false`)

`pdp-logs-*` (universal, segregate by `source`), `pdp-strangle-events-*`, `pdp-trades-*`,
`pdp-journal-*`, `pdp-backtest-{runs,days,trades,decisions,promotions}-*`.

## Rules / gotchas

- **Hot-path safe**: `enqueue` is sync, `put_nowait`, drop-on-full — never awaits, never blocks.
- **No feedback loop**: this module's logger is bound `_no_ship=True`; the processor skips it.
- **OS down = no-op**: flush failures log one warning and discard; the API + stdout logging are unaffected.
- **Dual-sink, not replace**: emit sites keep their JSONL/Mongo write and *additionally* enqueue.
- **Inactive in tests/scripts**: `get_active_indexer()` returns `None` unless the API lifespan started it.
- `opensearchpy` is imported lazily (inside functions) so the package imports without the dep / when disabled.
