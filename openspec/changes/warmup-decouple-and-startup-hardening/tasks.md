# Tasks

## 1. Decouple warmup from the trading-process boot path
- [x] 1.1 Add `reconcile: bool` to `warm_up_indicator_engine` / `_warm_one`
      (`pdp/indicators/warmup.py`); gate `_replace_derived_bars` + `_persist_bars` on it.
- [x] 1.2 Restrict the read-only (`reconcile=False`) Dhan top-up to short intraday
      timeframes (`_INTRADAY_TOPUP_TFS = {5m, 15m}`); higher TFs seed from stored bars only.
- [x] 1.3 `FeedEngineGroup.start` calls warmup with `reconcile=False` (`pdp/runtime/groups.py`).
- [x] 1.4 `scripts/warmup_premarket.py` calls warmup with `reconcile=True`.
- [x] 1.5 Remove `warmup_premarket.py` from `Taskfile.yml` `dev:trade` **and** `dev:engine`
      boot paths; add `--timeout-graceful-shutdown 20` to `dev:trade`'s uvicorn command.
- [x] 1.6 Tests: `reconcile=False` writes nothing; short-TF top-up fetches but does not
      persist; higher-TF top-up is skipped on boot (`tests/indicators/test_warmup.py`).

## 2. Premarket-ran marker + UI signal
- [x] 2.1 Shared `premarket_marker_key(ist_date)` in `warmup.py`.
- [x] 2.2 `scripts/warmup_premarket.py` sets `warmup:premarket:{ist_date}` (24h TTL) on done.
- [x] 2.3 `GET /api/v1/strangle/monitor` exposes `status.premarket`
      (`_get_premarket_status`, `pdp/strategy/routes.py`).
- [x] 2.4 Flutter `PremarketStatus` model + `MonitorSnapshot.premarket` parse
      (`execution_models.dart`); default "ran" when absent (no false banner on old backend).
- [x] 2.5 `_PremarketBanner` in the execution tab; hidden on the ran path.
- [x] 2.6 Tests: banner shows when not-run, hidden when ran/default
      (`app/test/strategy_execution_tab_test.dart`).

## 3. Container resource caps + healthcheck
- [x] 3.1 Mongo `cpus`/`mem_limit`/`--wiredTigerCacheSizeGB`; relaxed healthcheck +
      `start_period` (`infra/compose/docker-compose.yml`).
- [x] 3.2 Redis `maxmemory`+`mem_limit`; OpenSearch + Postgres `mem_limit`.

## 4. Bounded shutdown drains
- [x] 4.1 `BarWriter.stop(timeout_s=...)` bounds the final drain (`pdp/market/bar_writer.py`).
- [x] 4.2 `JournalService.stop(timeout_s=...)` bounds join + final flush
      (`pdp/journal/service.py`).
- [x] 4.3 Lifespan bounds each `group.stop` with `asyncio.wait_for` (`pdp/main.py`).
- [x] 4.4 Test: `BarWriter.stop` returns within its timeout on a wedged flush
      (`tests/market/test_bar_writer.py`).

## 5. Verification (live — next relaunch)
- [ ] 5.1 Restart stack with caps applied; a single `task dev:trade` boots read-only with no
      `indicator_warmup_derived_from_1m` write storm on the API path; `docker stats` mongo CPU
      stays under the 4-core cap; container `healthy`; `/readyz` green.
- [ ] 5.2 With premarket un-run, the execution panel shows the Premarket banner; after
      `task warmup`, the marker is set and the banner clears on the next monitor poll.
- [ ] 5.3 Stop `dev:trade` → process exits cleanly within ~25s (no SIGKILL).
- [ ] 5.4 `openspec archive warmup-decouple-and-startup-hardening`.
