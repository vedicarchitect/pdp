# Tasks — api-worker-decoupling

> **Assessment (2026-07-10 follow-up pass):** 5.1/5.2 (position snapshot publish + Redis-backed
> indicator reads) and 7.1/7.2 (docker-compose `engine`/`ops` services + healthchecks) landed —
> see per-task notes below. `backend/Dockerfile` (new, multi-stage `uv` build) + the compose
> `api`/`engine`/`ops` services were built and smoke-tested locally: `docker compose --profile
> app up -d api` served `/healthz` 200 and `/readyz` 503/`degraded` (`engine: down`) as designed;
> bringing up `engine` alongside it reached `engine_ready` (`live: false, broker: paper`) and
> connected to the real Dhan feed — both test containers were torn down immediately afterward to
> avoid duplicating whatever engine process may already be running against the same Postgres/
> Redis state. Full backend suite re-run 2026-07-10 (`DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` blanked
> as env overrides so route tests don't open a real Dhan feed): **925 passed, 42 failed** — all 42
> pre-existing (`PositionState` missing `strategy_id` ctor arg, per `backend/CLAUDE.md`'s debt
> note; Windows `ProactorEventLoop` asyncio teardown races, per `RUNBOOK.md`'s troubleshooting
> table), none in files touched by this change. `tests/orders/test_command_channel.py` (new,
> covers 8.1) is 3/3. What remains: `SELECT … FOR UPDATE` on the shared position write (5.3, P2)
> and a runtime cutover-verification of the Redis→WS bridge (3.2/8.3) — still deferred with
> `cloud-deploy-aws`.

## 1. Composable startup groups
- [x] 1.1 New `pdp/runtime/groups.py`: role-selected startup groups (`async start()/stop()`),
      extracted from `main.py` lifespan
- [x] 1.2 Per-group try/except (fault isolation)
- [x] 1.3 Lifespan selects groups by `PDP_ROLE`; `stop()` in reverse order

## 2. Entrypoints
- [x] 2.1 `pdp/runtime/entrypoints.py` with `pdp-api` / `pdp-engine` / `pdp-ops`
- [x] 2.2 Console scripts registered in `backend/pyproject.toml`
- [x] 2.3 `PDP_ROLE` (`Literal["all","api","engine","ops"]`) + per-process pool settings

## 3. Redis→WS bridge (API)
- [x] 3.1 Bridge task in `pdp/runtime/bridge.py` (`SUBSCRIBE tick.*` + `XREAD bars.*` → WSHub)
- [~] 3.2 Remove in-process `WSHub` calls from `TickRouter` — **verify cutover at runtime**
      (bridge exists; confirm the engine role no longer double-serves WS)
- [x] 3.3 Same bridge pattern for job-progress / alerts / events hubs

## 4. Order command channel
- [x] 4.1 `orders/command_channel.py`: `OrderCommand`/`OrderResult` + Stream producer/consumer
      group with `cmd_id` SETNX idempotency
- [x] 4.2 API mutating order routes enqueue + await result (503 on engine-down / ack timeout)
- [x] 4.3 Engine runs single margin + kill-switch gate before broker placement
- [x] 4.4 Kill-switch is a high-priority command; engine is sole square-off authority

## 5. State snapshots
- [x] 5.1 Engine publishes `indicators:<sid>:<tf>` + `position:<...>` + `engine:status`
      — **FIXED 2026-07-10**: added `PortfolioService._publish_position_snapshots()`
      (`position:<strategy>:<sid>` hash, EX 30s), wired into the 5s `_run_flush()` loop
      (not the tick hot path). `engine:status` and `ind:`/`st:` indicator snapshots already
      existed (`market/router.py`, bar close).
- [x] 5.2 API read endpoints read snapshots; durable reads stay on PG
      — **FIXED**: `strategy/routes.py` now has `_build_indicator_cell` dispatch to
      `_build_indicator_cell_inproc` (in-process engine, zero-latency) or
      `_build_indicator_cell_from_redis` (parses `ind:`/`st:` snapshots) depending on
      whether an engine is attached; `_get_matrix_futures_sids` mirrors
      `engine.matrix_futures_sids` to Redis (`matrix:futures_sids`, published once at
      startup by `FeedEngineGroup`) for the no-engine case.
- [ ] 5.3 `SELECT … FOR UPDATE` on the position write if engine + MTM both write it (P2) — **DEFERRED**

## 6. Degradation + pools
- [x] 6.1 Per-role `/readyz`; engine-down → stale-flagged snapshots + "feed offline" banner
- [x] 6.2 Per-process PG/Mongo pool budgeting within `max_connections`
- [x] 6.3 Non-blocking warmup: engine boots `status: warming`, strategies disarmed until ready

## 7. Infra + Flutter
- [x] 7.1 `infra/compose/docker-compose.yml`: add `engine` + `ops` services (same image, `command:`)
      — **DONE 2026-07-10**: new `backend/Dockerfile` (multi-stage `uv` build, non-root, `curl`
      for healthchecks) + `api`/`engine`/`ops` services added behind a new `app` compose profile
      (`docker compose --profile app up -d`) so plain infra-only `task db:up` is unaffected and
      `api`'s `8000:8000` never collides with `task dev`'s host uvicorn. `DATABASE_URL`/
      `REDIS_URL`/`MONGO_URI`/`OPENSEARCH_URL` are overridden to the compose network service
      names (`postgres`/`redis`/`mongo`/`opensearch`) since `backend/.env`'s values are
      host-mapped `localhost` ports that don't resolve inside the compose network;
      `pdp/runtime/entrypoints.py` normalized all three roles to port 8000 (was 8001/8002/8003,
      inconsistent with `/readyz` and `task dev`). Built + boot-tested locally, see top note.
- [x] 7.2 Compose healthchecks target `/readyz` — **DONE**: `curl -f http://localhost:8000/readyz`
      on all three services, matching design.md.
- [x] 7.3 Flutter: stale banner + `503` handling on manual order when engine down

## 8. Tests + validation
- [x] 8.1 Tests: boot-without-engine, group-isolation, command roundtrip + idempotency + 503,
      snapshot read
      — **FIXED 2026-07-10**: group-isolation tests already existed
      (`test_lifespan_required_groups.py`). Added `tests/orders/test_command_channel.py`
      (roundtrip, idempotent-redelivery, rejected-when-engine-down) — 3/3 pass. Writing this
      test also surfaced and fixed a real race-condition bug in `CommandProducer.execute()`:
      it re-resolved literal `"$"` on every `XREAD` poll instead of anchoring to a concrete
      stream ID once, so a fast engine's result could land in the gap and be permanently
      missed, misreporting a placed order as `"rejected"`/timeout.
- [x] 8.2 `task test` green; `flutter analyze && flutter test` green
- [~] 8.3 Manual 3-process boot — re-run after the 3.2 cutover check
- [x] 8.4 `openspec validate --strict api-worker-decoupling` passes
