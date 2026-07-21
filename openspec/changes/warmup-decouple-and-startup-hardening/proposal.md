# warmup-decouple-and-startup-hardening

## Why

On 2026-07-21 (market hours) `pdp-mongo` spiked past **1000% CPU** (of 800% / 8 cores),
health flapped `unhealthy`, and the trading process hung on shutdown (forcing SIGKILL).
The spike **recurred with a single backend process** and **Mongo stayed ~900% even after
the API was stopped** — proving the load is *server-side in-flight Mongo work*, not client
traffic, i.e. a **write-amplification problem, not a capacity problem** (8 cores / 7.2 GB
is ample for this workload).

Root cause: the write-heavy indicator **warmup reconcile runs on the trading process's
boot path** — and, because `Taskfile.yml` `dev:trade` ran `warmup_premarket.py` and then
uvicorn (whose `FeedEngineGroup` re-ran the identical `warm_up_indicator_engine`), it ran
**twice** every launch. `warm_up_indicator_engine` interleaves engine-seeding reads with a
`delete_many` over a ~200-day window on the `market_bars` **timeseries** collection
(`_replace_derived_bars`) then re-inserts — and on a timeseries collection every delete
forces a decompress→rewrite of the containing bucket. Those large deletes pile up
server-side and keep grinding after the client is killed. Compounding it: no container CPU/
memory caps (Mongo sized its WiredTiger cache to the whole host), a Mongo healthcheck that
spawned `mongosh` every 5s with a 3s timeout and no `start_period` (so the check itself
timed out under load → false `unhealthy`), and two un-timeout-bounded `await`s on Mongo
flushes during shutdown (`BarWriter.stop`, `JournalService.stop`) with uvicorn started
without `--timeout-graceful-shutdown`.

Per the user's directive: **decouple warmup from API startup.** The deep-history reconcile
belongs to a standalone premarket job, not the trading process's critical boot path; the
API should boot fast and read-only, and the UI should flag a session that started without a
premarket run. Intraday trading only needs the short-timeframe current data (cheap), so
decoupling never impacts intraday.

## What Changes

- **Warmup gains a `reconcile` flag.** `warm_up_indicator_engine(..., reconcile: bool)`:
  - `reconcile=True` (standalone premarket job, `scripts/warmup_premarket.py`) keeps the
    write-heavy derive-from-1m reconcile (`_replace_derived_bars`/`_persist_bars`) — it owns
    the deep higher-timeframe history.
  - `reconcile=False` (trading process boot, `FeedEngineGroup`) seeds the engine read-only —
    it may derive higher-TF bars *in memory* to seed but never deletes/inserts on
    `market_bars`; only short intraday timeframes (`5m`/`15m`) may fetch a bounded Dhan
    top-up (not persisted) when stored depth is short. Higher-timeframe depth is the
    premarket job's responsibility.
- **`dev:trade` no longer runs warmup** — it boots read-only and adds
  `--timeout-graceful-shutdown 20`. Deep warmup is the separate `task warmup` (unchanged
  script, now the sole owner of the reconcile).
- **Premarket-ran marker + UI signal.** The premarket job records a Redis marker
  (`warmup:premarket:{ist_date}`, 24h TTL). `GET /api/v1/strangle/monitor` exposes a global
  `status.premarket` object; the execution panel shows a prominent banner recommending
  `task warmup` when today's run is missing. Intraday trading is never blocked by a missing
  run — higher-timeframe indicators simply read `--` until it runs.
- **Container resource caps** (`infra/compose/docker-compose.yml`): Mongo `cpus: 4.0`,
  `mem_limit: 3g`, explicit `--wiredTigerCacheSizeGB 1.5`, and a relaxed healthcheck
  (`interval 30s`, `timeout 10s`, `start_period 60s`); Redis `maxmemory 512mb` + `768m`;
  OpenSearch `1.5g`; Postgres `1g`.
- **Bounded shutdown drains.** `BarWriter.stop`/`JournalService.stop` bound their final Mongo
  flush with `asyncio.wait_for`; the lifespan bounds each group's teardown — a pegged Mongo
  can no longer hang process exit.

## Impact

- **Specs:** `indicator-warmup` (MODIFIED — reconcile decoupled from boot),
  `strategy-execution-monitor` (ADDED — premarket signal).
- **Code:** `pdp/indicators/warmup.py`, `pdp/runtime/groups.py`, `scripts/warmup_premarket.py`,
  `Taskfile.yml`, `pdp/market/bar_writer.py`, `pdp/journal/service.py`, `pdp/main.py`,
  `pdp/strategy/routes.py`, `infra/compose/docker-compose.yml`,
  `app/lib/features/manage/{domain/execution_models.dart,presentation/tabs/strategy_execution_tab.dart}`.
- **Behavior:** trading-process boot no longer writes `market_bars` (no reconcile delete on
  the hot path); premarket deep-history reconcile is a separate, explicitly-run job.
- **Out of scope (follow-ups):** the premarket-job N+1 + reconcile-window bounding (folds
  into `bar-warmup-reconcile-from-1m`); the `market_bars` granularity migration + secondary
  index + TTL + `minPoolSize` (new off-hours change `market-bars-schema-hardening`).
