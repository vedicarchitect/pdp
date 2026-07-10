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
> covers 8.1) is 3/3.
>
> **Closeout (2026-07-10, same day):** all remaining items closed — 3.2 (dead code + stale docs
> cleanup + regression test), 5.3 (`.with_for_update()` row lock on the real intra-engine race),
> and 8.3 (genuine 3-process boot verified without touching the host network — see 8.3 note; also
> surfaced and fixed a real `/readyz` bug where a stray `.decode()` on an already-decoded Redis
> string masked "ready" as 503/degraded). Nothing deferred to `cloud-deploy-aws` remains from this
> change.

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
- [x] 3.2 Remove in-process `WSHub` calls from `TickRouter`
      — **FIXED 2026-07-10**: cutover was already done in code (`TickRouter.__init__` never took
      a `ws_hub` param); `FeedEngineGroup.start()` still fetched a dead, never-used
      `ws_hub = getattr(app.state, "ws_hub", None)` local — removed. Fixed the stale docstring in
      `pdp/market/router.py` and the stale hot-path diagram in `pdp/market/CLAUDE.md`, both of
      which still described `TickRouter` calling `WSHub.broadcast()` directly. Added
      `tests/market/test_router.py` (2 tests) asserting `TickRouter` has no `ws_hub`
      param/attribute, locking in the contract that WS fan-out is API-process-only via
      `MarketBridge`.
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
- [x] 5.3 `SELECT … FOR UPDATE` on the position write if engine + MTM both write it (P2)
      — **FIXED 2026-07-10**: audited every read-modify-write site touching `orders.Position`.
      Engine (`net_qty`/`avg_price`/`realized_pnl`) and MTM (`portfolio/service.py`'s
      `_flush_dirty`, `unrealized_pnl`/`updated_at` only) are column-disjoint and already safe —
      Postgres's own row lock serializes the two `UPDATE`s regardless. The real hazard is
      **intra-engine**: `DhanBroker._on_alert` spawns an unbounded `asyncio.create_task` per
      order-update webhook with no per-sid serialization, so two `TRADED` alerts for the same
      `(strategy_id, security_id, exchange_segment, product)` arriving close together can both
      `SELECT` the same stale row and the second commit clobbers the first (lost `net_qty`/
      `avg_price`/`realized_pnl` update). Added `.with_for_update()` to the `select(Position)` in
      `upsert_position()` (`pdp/orders/paper.py`, shared by `PaperBroker` + `DhanBroker`) to close
      it. `tests/orders/` (39/39) green after the change.

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
- [x] 8.3 Manual 3-process boot — re-run after the 3.2 cutover check
      — **FIXED 2026-07-10**: booted `api`+`engine`+`ops` from `infra/compose/docker-compose.yml`
      (`--profile app`) with a `!override`-tag compose override stripping `api`'s host port
      entirely (`ports: !override []`) so the test never touched the host's port 8000 — verified
      via `docker port` (no mappings) before and after. Checked all three roles' `/readyz` via
      `docker exec <container> curl localhost:8000/readyz` (in-network, no host exposure):
      surfaced a real latent bug — `main.py`'s `/readyz` called `val.decode("utf-8")` on the
      `engine:status` Redis read, but the client is constructed with `decode_responses=True`
      (already returns `str`), so any time `engine:status` actually had a value the check raised
      `AttributeError` and reported `redis: "error: AttributeError"`/503, permanently masking a
      real "ready" state. Fixed by dropping the redundant `.decode()`. Rebuilt the shared image,
      re-ran: all three roles now `{"status":"ready","db":"ok","redis":"ok","mongo":"ok",
      "engine":"ready"}` (200), confirming the engine's `engine:status` Redis publish is correctly
      visible cross-process to api/ops — the core claim of this change. Engine logs confirm
      `live: false, broker: paper, strategy_registry_loaded count: 0` (no `strategies/` dir in the
      image → structurally no auto-start, no Dhan connection opened). Containers torn down
      immediately after; host port 8000 (pre-existing dev process) confirmed untouched throughout.
- [x] 8.4 `openspec validate --strict api-worker-decoupling` passes
