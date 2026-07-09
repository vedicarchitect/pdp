# Tasks — api-worker-decoupling

> **Assessment (2026-07-09 verification pass):** the *code* split has largely landed —
> `pdp/runtime/{groups,entrypoints,bridge}.py`, `pdp/orders/command_channel.py`, the
> `PDP_ROLE` setting, per-role `/readyz`, engine snapshots, non-blocking warmup, and the
> Flutter stale-banner all exist. What remains is **infra + one DB-safety item**, none of
> which is on the paper-tracking critical path: docker-compose `engine`/`ops` services
> (7.1/7.2), `SELECT … FOR UPDATE` on the shared position write (5.3), and a runtime
> cutover-verification of the Redis→WS bridge (3.x). These are deferred with `cloud-deploy-aws`.

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
- [x] 5.2 API read endpoints read snapshots; durable reads stay on PG
- [ ] 5.3 `SELECT … FOR UPDATE` on the position write if engine + MTM both write it (P2) — **DEFERRED**

## 6. Degradation + pools
- [x] 6.1 Per-role `/readyz`; engine-down → stale-flagged snapshots + "feed offline" banner
- [x] 6.2 Per-process PG/Mongo pool budgeting within `max_connections`
- [x] 6.3 Non-blocking warmup: engine boots `status: warming`, strategies disarmed until ready

## 7. Infra + Flutter
- [ ] 7.1 `infra/compose/docker-compose.yml`: add `engine` + `ops` services (same image, `command:`)
      — **NOT DONE** (no engine/ops services present); belongs with `cloud-deploy-aws`
- [ ] 7.2 Compose healthchecks target `/readyz` — **NOT DONE** (blocked on 7.1)
- [x] 7.3 Flutter: stale banner + `503` handling on manual order when engine down

## 8. Tests + validation
- [x] 8.1 Tests: boot-without-engine, group-isolation, command roundtrip + idempotency + 503,
      snapshot read
- [x] 8.2 `task test` green; `flutter analyze && flutter test` green
- [~] 8.3 Manual 3-process boot — re-run after the 3.2 cutover check
- [x] 8.4 `openspec validate --strict api-worker-decoupling` passes
