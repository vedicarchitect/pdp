## Why

Logs are fragmented across the platform: API/service logs print to stdout as `structlog`
JSON, `DirectionalStrangle` writes JSONL files, `JournalService` upserts Mongo
`paper_journal`, backtests land in Mongo `backtest_*`, and the Flutter app's logs never
leave the device. There is no single place to search, correlate, or build dashboards on top
of "what the platform did" — across the API, the strategy, trades, backtests, and the UI.

The chunk-4 structured strangle log proved the value of canonical events; this chunk makes
*every* log queryable. The payoff is twofold: (1) a unified operational view — one search
surface for every source, segregated by `source`, with realtime dashboards; and (2) the
trade-analysis feedback loop — the strategy's per-bar decisions become aggregatable, so
"was the bias bucket predictive?", "did the stop-gate help?", and per-bucket win-rates are
answerable, and Claude can be fed a bar-anchored session narrative built straight from the
queryable store.

## What Changes

A **unified OpenSearch log pipeline**. Every log — API request logs, service/strategy logs,
journal, backtest, market/orders, and Flutter UI logs — auto-publishes to OpenSearch in
realtime through **one** path, with **no manual export step anywhere**, segregated by a
`source` field.

- A `structlog` processor ships *every* backend log record to a universal `pdp-logs-*` index
  (Tier A), via a single non-blocking `OpenSearchIndexer` (enqueue-only, off the hot path).
- High-value events also route to strict-mapped **typed analytics indices** (Tier B):
  `pdp-strangle-events-*`, `pdp-trades-*`, `pdp-journal-*`, `pdp-backtest-{runs,days,trades}-*`.
- Flutter UI logs reach the same pipeline via `POST /api/v1/logs/ingest` from an app-side
  `LogShipper` (fire-and-forget, `source=ui`).
- OpenSearch Dashboards saved-objects (NDJSON, dashboards-as-code) provide 8 dashboards
  incl. a Unified Log Explorer, Bias Effectiveness, Backtest Explorer, and UI Health.
- A `GET /api/v1/analysis/session?date=…` endpoint rebuilds the bar-anchored Claude analysis
  narrative by querying OpenSearch.

This **supersedes** the previously-designed flat-file JSON/Markdown export — analysis is now
served from the queryable store, not generated files. JSONL/Mongo remain the source of
truth; OpenSearch is the derived, queryable, realtime layer. Dev runs a single-node
OpenSearch in `infra/compose/`; production maps to AWS OpenSearch Service by env URL swap
(chunk 16).

## Capabilities

### New Capabilities

- `trade-analysis-feedback-loop`: a unified OpenSearch log pipeline (universal `structlog`
  shipper + non-blocking indexer + typed analytics sinks + UI log ingest endpoint), index
  templates/mappings for logs + four analytics domains, dashboards-as-code, a log-search +
  session-narrative REST API, and a Claude review prompt template — all auto, realtime,
  segregated by `source`.
