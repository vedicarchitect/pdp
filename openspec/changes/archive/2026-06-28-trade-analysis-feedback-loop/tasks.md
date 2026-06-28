## 1. Infra + dependencies
- [x] 1.1 Add single-node `opensearch` (security disabled for dev) + `opensearch-dashboards` (`profiles: ["tools"]`) + named volume to `infra/compose/docker-compose.yml`
- [x] 1.2 Add `opensearch-py` to `backend/pyproject.toml`; `uv sync`
- [x] 1.3 Add `search:up` (compose up opensearch) + `search:init` (ensure templates + import dashboards) to root `Taskfile.yml`

## 2. Settings
- [x] 2.1 Add `OPENSEARCH_*` fields to `pdp/settings.py` (`ENABLED`, `URL`, `USER`, `PASSWORD`, `VERIFY_CERTS`, `INDEX_PREFIX`, `BULK_INTERVAL`, `BULK_MAX`, `QUEUE_MAX`, `LOG_LEVEL`)

## 3. Core pipeline (`pdp/observability/`)
- [x] 3.1 `client.py` — `get_opensearch()` async singleton + enable/disable guard
- [x] 3.2 `indexer.py` — `OpenSearchIndexer`: queue, bulk-flush loop, non-blocking `enqueue` with drop-on-full, lifespan start/stop
- [x] 3.3 `mappings.py` — index templates for `pdp-logs-*` + the 6 typed analytics indices + idempotent `ensure_templates()`
- [x] 3.4 `processor.py` — `opensearch_sink` structlog processor (source derivation, level floor, self-skip); wire into `pdp/logging.py` chain before `JSONRenderer`

## 4. Typed sinks + wiring
- [x] 4.1 `sinks.py` — `strangle_event_doc`, `fill_doc`, `journal_day_doc`, `backtest_run_doc`/`_day_doc`/`_trade_doc`
- [x] 4.2 Dual-sink `StrategyDailyLog.write()` → enqueue `strangle_event_doc` (indexer injected; no-op when absent)
- [x] 4.3 Dual-sink `JournalService._flush()` → enqueue `fill_doc` + `journal_day_doc`
- [x] 4.4 Dual-sink `BacktestStore` upserts → enqueue backtest docs

## 5. UI log ingest
- [x] 5.1 `ingest.py` — `POST /api/v1/logs/ingest` batch endpoint (validate, `source=ui`, enqueue)
- [x] 5.2 Flutter `LogShipper` in `app/` — batch + fire-and-forget POST; wire into app logger bootstrap

## 6. Query + REST
- [x] 6.1 `query.py` — log search helpers + `build_session(strategy_id, date)` (bar-anchored) from `pdp-strangle-events-*`
- [x] 6.2 `routes.py` — `/api/v1/observability/*` log search + `GET /api/v1/analysis/session?date=` (404 when empty)
- [x] 6.3 Register routers + bootstrap `ensure_templates()` and start/stop the indexer in `pdp/main.py` lifespan

## 7. Dashboards + prompt
- [x] 7.1 Author + export 8 dashboards' NDJSON to `infra/opensearch/dashboards/` (Unified Log Explorer, Live Strategy Session, Bias Effectiveness, Trade Blotter & P&L, Journal Analytics, Backtest Explorer, Live↔Backtest Parity, UI Health)
- [x] 7.2 `scripts/analysis/strangle_review_prompt.md` — Claude review prompt template (narrative from OS)

## 8. Tests
- [x] 8.1 `test_processor.py` — record→doc shape, source derivation, observability self-skip
- [x] 8.2 `test_indexer.py` — enqueue non-blocking, drop-on-full, bulk flush, OS-down no-op
- [x] 8.3 `test_sinks.py` — typed mapper outputs + idempotent ids
- [x] 8.4 `test_ingest_route.py` — valid batch accepted (`source=ui`), malformed → 422
- [x] 8.5 `test_analysis_routes.py` — session narrative on seeded index, 404 on empty

## 9. Docs
- [x] 9.1 `docs/RUNBOOK.md` — new § 18 (pipeline overview, `OPENSEARCH_*`, `search:up`/`search:init`, dashboards)
- [x] 9.2 Update `backend/CLAUDE.md` module map + dev-activity row; add `pdp/observability/CLAUDE.md`; note module in root `CLAUDE.md`
