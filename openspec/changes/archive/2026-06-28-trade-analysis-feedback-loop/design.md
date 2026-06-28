## Context

The platform produces logs in five disconnected places: `structlog` JSON to stdout (API +
all services), `StrategyDailyLog` JSONL files (`backend/pdp/strategy/log.py`, 12 canonical
`StrangleEventType` events), `JournalService` → Mongo `paper_journal`
(`backend/pdp/journal/service.py`), `BacktestStore` → Mongo `backtest_runs/days/folds/trades`
(`backend/pdp/backtest/store.py`), and Flutter app logs that stay on-device.

This chunk unifies them into one realtime, queryable OpenSearch pipeline, segregated by a
`source` field, with dashboards. It supersedes the originally-planned flat-file JSON/Markdown
export.

## Goals / Non-Goals

**Goals:**
- One pipeline: every backend log record auto-ships to OpenSearch via a `structlog` processor.
- Typed analytics indices for strangle-events, trades, journal, backtests (dashboards/aggregation).
- Flutter UI logs reach the same pipeline through a batch ingest endpoint.
- Hot-path-safe, non-blocking shipping; OpenSearch being down never affects trading or the API.
- Dashboards-as-code (NDJSON) + a log-search/session-narrative REST API.
- Claude session narrative rebuilt by querying OpenSearch.

**Non-Goals:**
- Historical backfill of existing JSONL/Mongo logs into OpenSearch (live pipeline only;
  a backfill shipper is a deferrable follow-up).
- Flutter dashboard *screens* (chunks 8/10/14 read this layer).
- AWS OpenSearch provisioning (chunk 16 — env URL swap).
- Replacing JSONL/Mongo as systems of record (OpenSearch is derived, not the SoT).

## Decisions

### D1 — `pdp/observability/` module

New importable module under `backend/pdp/observability/`: `client.py` (async OpenSearch
singleton), `indexer.py` (the single sink), `processor.py` (universal structlog shipper),
`mappings.py` (index templates), `sinks.py` (typed doc mappers), `ingest.py` (UI log
endpoint), `query.py` (search + session builder), `routes.py` (REST). One module so the
processor, typed sinks, ingest endpoint, and routes all share one client + one indexer.

### D2 — A single non-blocking `OpenSearchIndexer` is the only sink

Mirrors `JournalService`: an `asyncio.Queue(maxsize=OPENSEARCH_QUEUE_MAX)`, a background
bulk-flush loop (flush on `OPENSEARCH_BULK_INTERVAL` or when `OPENSEARCH_BULK_MAX` is
reached), lifespan-managed start/stop. `enqueue(index, doc, doc_id=None)` is **non-blocking**
(`put_nowait`, **drop-on-full** with a counter) so it can be called from the `structlog`
processor on the hot path without ever awaiting or blocking (non-negotiable #5). When
OpenSearch is unreachable the flush logs one warning and discards the batch — the API keeps
serving and stdout logging is unaffected (JSONL/Mongo remain the SoT). **The observability
module's own logger is skipped** by the processor to prevent a ship→log→ship feedback loop.

### D3 — Universal `structlog` processor = Tier-A shipper

`opensearch_sink(logger, method_name, event_dict)` is inserted into the `configure_logging`
processor chain in `pdp/logging.py`, just before `JSONRenderer` (so it sees the structured
dict, not a rendered string). It enqueues a copy to `pdp-logs-*` with `@timestamp, source,
level, logger, event, service, env, request_id` + remaining bound context as a `flattened`
`context` object, then returns `event_dict` unchanged. `source` is derived from the logger
name/module, overridable via bound context (`log.bind(source="strategy")`). A min level
floor (`OPENSEARCH_LOG_LEVEL`) keeps volume sane. Honors non-negotiable #6 (structlog only —
we extend it, never `print`).

### D4 — Typed Tier-B sinks + composable index templates + idempotent ids

`sinks.py` provides pure mappers (`strangle_event_doc`, `fill_doc`, `journal_day_doc`,
`backtest_run_doc`/`_day_doc`/`_trade_doc`). The existing emit sites dual-sink: keep their
current durable write (JSONL/Mongo) **and** enqueue the typed doc. `mappings.py` registers
composable index templates with `dynamic:false` and explicit types (money=`double`,
ids=`keyword`, times=`date`, free text=`text`, nested config/votes=`object`/`flattened`).
`ensure_templates()` is idempotent and runs at lifespan start. Idempotent `doc_id`s allow
safe re-index: events=`strategy_id:ist_time:event_type:sid`, journal=`date`,
backtest=`run_id` (or `run_id:date`); Tier-A logs use auto ids. Monthly date-suffixed
indices (`-YYYY.MM`) keep shards small and make retention trivial.

### D5 — UI logs via `POST /api/v1/logs/ingest` + Flutter `LogShipper`

A batch endpoint validates and feeds UI/external records into the same indexer with
`source=ui` (plus `screen`, `level`, `build`, `device`). An app-side `LogShipper` (`app/`)
batches the app's logs and POSTs on an interval/size threshold, fire-and-forget — never
blocks the UI (non-negotiable #9). This closes the "everything in one place" loop.

### D6 — Single-node compose now, AWS OpenSearch later

`infra/compose/docker-compose.yml` gains a single-node `opensearch` (security plugin
disabled for dev) + `opensearch-dashboards` under `profiles:["tools"]`, with a named volume.
The client is env-configured, so chunk 16 swaps `OPENSEARCH_URL` to AWS OpenSearch Service
with no code change (non-negotiable #11).

### D7 — Dashboards-as-code

Eight dashboards authored once and exported as saved-object NDJSON under
`infra/opensearch/dashboards/`, imported idempotently by `task search:init`. Versioned,
repeatable, environment-independent.

### D8 — Claude narrative from OpenSearch (export superseded)

`query.build_session(strategy_id, date)` reconstructs the bar-anchored session (each
`bias_evaluated` anchors a bar; later events attach as actions) by querying
`pdp-strangle-events-*`, exposed at `GET /api/v1/analysis/session?date=…`. The flat-file
JSON/Markdown export and its CLI are dropped — the queryable store replaces them. The
`scripts/analysis/strangle_review_prompt.md` template still guides Claude's review.

## Risks / Trade-offs

- **Log volume / retention**: every record shipped could balloon storage. Mitigation: a
  level floor (`OPENSEARCH_LOG_LEVEL`), monthly indices, and ISM/manual rollover; Tier-B
  typed indices are low-volume by nature.
- **Processor overhead on the hot path**: the sink runs inside every logging call.
  Mitigation: it only does dict-copy + `put_nowait`; no I/O, no await; drop-on-full.
- **Feedback loop**: the indexer/flush logging itself could be re-shipped. Mitigation:
  the processor skips the observability logger namespace.
- **Mapping drift**: ad-hoc fields could break typed mappings. Mitigation: `dynamic:false`
  on typed indices (unknown fields ignored); the universal index keeps free context under a
  single `flattened` field.
- **Local resource use**: OpenSearch + Dashboards are heavier than Mongo/Redis. Mitigation:
  Dashboards behind the `tools` profile; single-node, modest JVM heap in compose.

## Open Questions

- None blocking. Retention policy (ISM days) can start permissive and tighten later.
