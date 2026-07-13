# test-suite-baseline-green — minimal context

Read only these. **Task 1 (measure the baseline) blocks everything else.**

| File | Why |
|------|-----|
| `backend/tests/risk/test_loss_cap.py` | All 11 tests fail on fixture construction — the largest cluster, and safety-critical |
| `backend/pdp/portfolio/` | `PositionState` — decide whether the required `strategy_id` was correct |
| `backend/pdp/risk/` | `KillSwitchService`, hard day-loss cap — what those 11 tests guard |
| `backend/tests/strategy/test_directional_strangle.py` | `:953, :979, :1003, :1025` assert an event **by name** that covers three conditions |
| `backend/pdp/runtime/groups.py` | `required` groups — the startup invariant test |
| `backend/CLAUDE.md` | The "pre-existing debt" paragraph to delete |
| `Taskfile.yml` | `test` must fail the build |

## Key facts established during investigation
- Two failure counts are in circulation and cannot both be right: **27** (`backend/CLAUDE.md`) and
  **45 failed / 948 passed** (last full run in this tree). Measure before fixing.
- `tests/risk/test_loss_cap.py`: **11/11 fail**, all
  `TypeError: PositionState.__init__() missing 1 required positional argument: 'strategy_id'`.
  This file tests the day-loss cap — the mechanism that halted BANKNIFTY on **phantom** P&L on
  2026-07-08. A safety mechanism whose tests do not run is not tested.
- The suite tests that code *runs*, not that invariants *hold*. Three live bugs prove it: a dead
  import silently killed two runtime groups; `_rehydrate_legs` reads a collection nothing writes;
  four assertions check an event name that covers three unrelated conditions.
- Dart side is healthy: `flutter analyze` = 7 `info`, 0 errors; `flutter test` = 28 passing. A sweep,
  not a rescue.
- 267 ruff items are **out of scope** here. Record the count; separate pass.

## Related
`[[dead_command_channel_import]]`, `[[execution_daily_parity]]`,
`[[leg_rehydration_misclassification_bug]]`.
A red baseline cannot detect a regression — land this before the five strategy/data changes, so their
verification means something.

## Baseline inventory (task 1) — measured 2026-07-10

**Neither figure in circulation was right.** Measured baseline: `uv run pytest -q` →
**43 failed, 965 passed**, 237 warnings, 584.65s. (Not 27 per `backend/CLAUDE.md`, not 45 per the
"last full run.")

**Ruff**: `uv run ruff check .` → **646 errors** (290 auto-fixable), not the 267 documented in
`backend/CLAUDE.md`. Out of scope per §7 — recorded here for tracking only, not fixed.

**Flutter baseline** (`cd app && flutter analyze` / `flutter test`) — matches the documented
expectation exactly: **7 `info`, 0 errors**; **28/28 tests passing**.

### Failure clusters (43 node ids → 6 clusters), all resolved, all real fixes (no strict-xfails needed)

| # | Cluster | Nodes | Root cause | Resolution |
|---|---------|-------|------------|------------|
| 1 | `tests/risk/test_loss_cap.py` (11) + `tests/portfolio/test_service.py` (9) + `tests/portfolio/test_snapshot.py` (1) | 21 | `PositionState` gained a required `strategy_id` field (migration 0012, keys the position cache by `(strategy_id, security_id, exchange_segment, product)`) — production is correct, test fixtures never updated | Added `strategy_id="test-strategy"` to the `_pos()`/`_make_pos()`/`_make_pos_state()` helpers in all three files |
| 2 | `tests/portfolio/test_routes.py` (4) | 4 | Tests called route functions directly (bypassing FastAPI DI) with stale args, and parsed a raw `.body` JSON shape (`{"positions": [...], "count": N}`) the routes no longer return — routes now return typed Pydantic `Page[PositionOut]` / `SummaryOut` | Rewrote the test file: `PaginationParams(limit=50, offset=0)` passed explicitly (bare `PaginationParams()` leaves FastAPI `Query()` sentinels that break SQLAlchemy `.offset()`), assertions moved onto the returned Pydantic model attributes |
| 3 | `tests/options/test_routes.py` (5), `tests/positional/test_routes.py` (3), `tests/intel/test_routes.py` (1), `tests/market/test_bars_route.py` (1), `tests/observability/test_ingest_route.py` (2 — see cluster 5) | 12 | Documented gap in `tests/conftest.py`'s `mock_mongo_lifespan`: it patched `pdp.main.mongo_connect`/`init_collections`/`mongo_disconnect`, but the real lifespan startup lives in `pdp.runtime.groups.InfraGroup` (`pdp.main.lifespan` just delegates to `GROUPS_BY_ROLE`), which holds its **own** `from ... import ... as ...` name bindings — patching `pdp.main`'s copies never intercepted full-lifespan (`TestClient(app)`-context) tests, so `app.state.mongo_db` was a real Motor database | Added matching `patch("pdp.runtime.groups.mongo_connect"/`init_collections`/`mongo_disconnect", ...)` alongside the existing `pdp.main` patches in the one shared `mock_mongo_lifespan` fixture |
| 4 | `tests/indicators/test_warmup.py` (1) | 1 | Test called the obsolete 3-arg `engine.seed_from_bars(sid, tf, [bar])`; production signature is `seed_from_bars(self, bars: list[BarClosed])` (`BarClosed` self-describes `security_id`/`timeframe`) | Fixed both call sites to the 1-arg form |
| 5 | `tests/jobs/test_runner.py` (2) | 2 | Windows asyncio-teardown race (documented in `backend/CLAUDE.md`): the global async engine singleton (`pdp/db/session.py`) binds to whichever event loop first used it; pytest-asyncio gives each test its own loop, so a later test reuses a pool bound to an already-closed loop (`Event loop is closed`) | Replicated the existing `_fresh_engine` autouse fixture pattern from `tests/broker_sync/conftest.py` into a new `tests/jobs/conftest.py` (dispose the engine before/after each test) |
| 6 | `tests/observability/test_ingest_route.py` (2) | 2 | Tests asserted `status_code == 200`; production (`pdp/observability/ingest.py:35`) deliberately declares `status_code=202` for this fire-and-forget batch-ingest endpoint (per its own docstring) — tests were stale, not production | Updated both assertions to expect `202` |
| 7 | `tests/test_app_start_log.py` (1) | 1 | `pdp.main.log` is a module-level structlog proxy shared for the whole test session. `cache_logger_on_first_use=True` (`pdp/logging.py`) makes a proxy monkeypatch its own `bind` on first use, permanently caching whichever processor chain was active then. An earlier test in the full suite already triggers the app lifespan (and this same `log.info("app_start", ...)` call) outside of `capture_logs()`, so by the time this test runs, `capture_logs()` can never see the event — passes standalone, fails in the full suite (`assert 0 == 1`) | Test clears the proxy's cached `bind` (`main_module.log.__dict__.pop("bind", None)`) before entering `capture_logs()`, forcing it to re-resolve against the active (capturing) processor chain |
| 8 | `tests/test_mongo.py` (2) | 2 | `readyz`'s Redis check (`pdp/main.py:198`) does `val = await app.state.redis.get(...)`; production's real Redis client is constructed with `decode_responses=True` (`pdp/runtime/groups.py:43`) so `val` is always `str`. The tests mocked `get` to return `bytes` (`b"ready"`) based on a stale comment claiming `readyz` calls `.decode()` — it doesn't, and never did in the current code — so the mocked `bytes` value flowed straight into `JSONResponse(content=...)` and blew up in `json.dumps` (`TypeError: Object of type bytes is not JSON serializable`) | Fixed the test mocks to return `"ready"` (str), matching what the real client actually returns; updated the stale comment |

One additional flake observed and **not** part of the 43: `tests/broker_sync/test_service.py` (5 tests)
errored once, immediately after the conftest fix, in one full-suite run; reran standalone (11/11 pass),
reran with `tests/backtest tests/broker_sync` together (255/255 pass), reran the full suite twice more
(0 errors both times, 1008 passed). Consistent with the pre-existing Windows asyncio-teardown note in
`backend/CLAUDE.md` — order-dependent, not reproducible, not chased further.

**Result**: `uv run pytest -q` → **1008 passed, 0 failed**, re-run twice for stability
(no `pytest-randomly` plugin installed — suite order is deterministic in this repo).
No `xfail` markers were needed; every cluster had an identifiable, fixable root cause. (Section 4
added 2 more strict-`xfail` tests naming `strangle-leg-state-durability` /
`strangle-observability-gaps` — final count **1010 passed, 2 xfailed**.)

## Post-verification fix (`/opsx:verify` finding)

`/opsx:verify` flagged that `--fatal-infos` (the flag that actually makes `flutter analyze` fail on
an `info`-level finding) only lived in `Taskfile.yml`'s `app:test` and CI — every developer-facing
doc (`app/CLAUDE.md`, root `CLAUDE.md`, `app/README.md`, `docs/RUNBOOK.md`) told people to run bare
`flutter analyze`, which would not catch a *new* info-level lint outside the two rules elevated to
`error` in `analysis_options.yaml`. Fixed by adding `--fatal-infos` to the command in all four docs,
so the command developers are actually told to run matches the real gate.
