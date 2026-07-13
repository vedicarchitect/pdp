# api-worker-decoupling

## Why

The API "often becomes stale and dies." Root cause: `backend/pdp/main.py`'s `lifespan()` is one
~550-line function that starts ~20 subsystems sequentially — market feed, indicator warmup,
strategies, intel scrapers (yfinance/feedparser/nsepython), schedulers, ML jobs, and WS serving —
**all in one process, most with no per-subsystem try/except**. One flaky Dhan-feed or warmup call
crashes the whole process, taking the dashboard and backtest console down with it. There is no
fault isolation and no graceful degradation.

This is not a new idea: the ratified `repo-architecture` spec already requires that *"the strategy
worker SHALL remain a separately-launchable process decoupled from the API,"* and the stubbed
`cloud-deploy-aws` change already scopes *"containerize the API + strategy worker."* This change
implements that separation.

Crucially, the hard part is already built: `market/router.py` (`TickRouter`) already publishes
the hot path to Redis (`SET ltp:<sid>`, `PUBLISH tick.<sid>`, `XADD bars.<sid>.<tf>`). What keeps
everything in one process is only that the *consumers* (`WSHub`, `IndicatorEngine`, `StrategyHost`,
alerts) are invoked by in-process method call instead of subscribing to Redis.

## What Changes

- **Refactor the monolithic `lifespan()` into composable startup groups** — each a small object
  with `async start()`/`async stop()` (single-responsibility): `infra` (PG/Mongo/Redis/OpenSearch),
  `web` (routers + WS endpoints + Redis→WS bridge), `feed_engine` (Dhan feed + tick router +
  bars + indicators + warmup + strategies + execution), `ops` (intel poller + schedulers + chain
  poller + events), `job_runner` (ML train + backfill). Each group is wrapped in its own
  try/except so one failure degrades that group, not the process.
- **Three launchable entrypoints on one image:** `pdp-api` (groups: infra+web), `pdp-engine`
  (infra+feed_engine), `pdp-ops` (infra+ops+job_runner).
- **Centralize live order placement in the engine** (single kill-switch + margin authority). The
  API validates a manual order (reusing change #1's models) and enqueues it on a **Redis Stream +
  consumer group**; the engine consumes, runs the single margin/kill-switch gate, places to the
  broker, and writes an ack/result back. An idempotency key prevents double-fill on engine
  restart. The kill-switch is a high-priority command on the same channel.
- **Redis→WS bridge in the API** — replace `TickRouter`'s in-process
  `WSHub.publish_tick/publish_bar` with a bridge task that `SUBSCRIBE tick.*` + reads the `bars.*`
  streams and fans out to `WSHub` clients (the WS endpoints stay in the API). Same bridge pattern
  for the job-progress / alerts / events hubs.
- **Engine→Redis snapshot publishes** the API reads instead of in-process objects:
  `indicators:<sid>:<tf>` (on bar close) and `position:<...>` live MTM. Durable positions/orders
  stay read from PostgreSQL.
- **Non-blocking warmup** — the engine boots, publishes `status: warming`, and strategies stay
  disarmed (via change #4's `WARMUP_INCOMPLETE`) until warm, so slow/flaky warmup never blocks or
  crashes the process.
- **Graceful degradation** — per-process `/readyz` reflecting only that process's groups; engine
  down → the API serves last-known snapshots + a "feed offline" banner and returns `503` for
  manual orders.

## Impact

- **Affected specs:** `api-worker-decoupling` (new — process split, order command channel, WS
  bridge, snapshot contracts, degradation), and it satisfies the existing `repo-architecture`
  cloud-readiness requirement.
- **Affected code:** `backend/pdp/main.py` (lifespan → groups), new `pdp/runtime/` (group
  definitions + `pdp-api`/`pdp-engine`/`pdp-ops` entrypoints), `market/router.py` +
  `market/ws.py` (Redis→WS bridge), `orders/` (order command consumer/producer), `risk/`
  (kill-switch as command), `indicators/` + `portfolio/` (snapshot publish), `db/session.py` +
  `mongo/client.py` (per-process pool sizing), `infra/compose/docker-compose.yml` (3 services).
- **Reuses:** the existing Redis tick/bar pub-sub + streams in `market/router.py`; `WSHub`;
  `select_broker()`; change #1's validated order models; change #4's warmup-disarm events. Feeds
  the stubbed `cloud-deploy-aws` (its Docker/compose 3-service layout comes from here).
- **Infra:** docker-compose gains `engine` + `ops` services (same image, different command);
  no new managed AWS resource in this change (that lands in `cloud-deploy-aws`).
- **Depends on:** change #1 (validated API tier that enqueues order commands) + change #4 (warmup
  disarm events). Ship last.
