# Tasks — test-suite-baseline-green

> **Prerequisite:** `dev-reload-scoping`. You cannot iterate on tests while a file-watcher restarts
> the backend under you.
>
> **Land this before the strategy changes.** Their regression tests prove nothing about the rest of
> the system while 45 other tests are red.

## 1. Measure the real baseline (do this before touching anything)
- [x] 1.1 `cd backend` then `uv run pytest -q --no-header -p no:randomly 2>&1 | tail -40`
- [x] 1.2 Record the exact counts: passed / failed / errors / skipped. The two figures in circulation
      (27 in `backend/CLAUDE.md`, 45 from the last full run) cannot both be right.
- [x] 1.3 `uv run pytest -q --no-header --tb=no -rf` → capture every failing node id
- [x] 1.4 Group the failures into clusters by root cause; one line per cluster
- [x] 1.5 Write the inventory into this change's README. **Do not proceed without it** — otherwise
      there is no way to tell a fix from a coincidence.
- [x] 1.6 Record `uv run ruff check . | tail -1` (the 267-item count) — for tracking, not for fixing here
- [x] 1.7 `cd app` then `flutter analyze` and `flutter test` → record both baselines
      (expected: 7 `info`, 0 errors; 28 tests passing)

## 2. The loss-cap cluster (11 tests, safety-critical, first)
- [x] 2.1 `uv run pytest tests/risk/test_loss_cap.py -q` → all 11 fail with
      `TypeError: PositionState.__init__() missing 1 required positional argument: 'strategy_id'`
- [x] 2.2 **Decide whether the tests or the code are wrong.** `PositionState` gained a required
      `strategy_id`. Was that correct? Read `pdp/portfolio/` and the change that introduced it.
- [x] 2.3 If the production signature is right → update the fixtures
- [x] 2.4 If `strategy_id` should have had a default → the failing tests are a real API regression
      report; fix `pdp/portfolio/` instead
- [x] 2.5 Write down which it was, and why. This file guards the day-loss cap that misfired on
      phantom P&L on 2026-07-08 — a wrong call here is expensive.
- [x] 2.6 Assert the cap fires exactly once on breach, does not fire below the limit, and resets on
      day reset

## 3. The remaining clusters, largest first
- [x] 3.1 For each cluster: fix, or `@pytest.mark.xfail(strict=True, reason="<change-id>")`
- [x] 3.2 `strict=True` is not optional — an xfail that starts passing must fail the suite
      (moot here — every cluster got a real fix, no xfails were needed)
- [x] 3.3 Every xfail reason names a real, existing change id (n/a, see above)
- [x] 3.4 Treat each cluster as an unread bug report until proven otherwise. Some of the 45 may be
      correct about production code being wrong. (One was: `test_mongo.py`'s readyz tests correctly
      caught that its own mock diverged from what production's `decode_responses=True` Redis client
      actually returns — fixed the mock, not production, since production was right.)
- [x] 3.5 Windows note: `backend/CLAUDE.md` records an asyncio-teardown race on Windows. Confirm
      whether any cluster is that, and if so run it under WSL2 before declaring it environmental.
      (`tests/jobs/test_runner.py` was this race — fixed with the same `_fresh_engine` pattern
      already established in `tests/broker_sync/conftest.py`, no WSL2 needed.)

## 4. Add the three invariant tests whose absence let real bugs ship
- [x] 4.1 `tests/test_runtime_groups.py`: every group with `required = True` constructs and starts.
      This would have caught `command_channel.py` importing a nonexistent `OrderRequest`, which killed
      `WebGroup` + `FeedEngineGroup` on every boot for weeks.
- [x] 4.2 `tests/strategies/test_leg_rehydration.py`: a leg survives a restart with its type intact.
      Owned by `strangle-leg-state-durability`; add the failing test here and let that change fix it
      (mark `xfail(strict=True, reason="strangle-leg-state-durability")`).
- [x] 4.3 `tests/strategies/test_event_taxonomy.py`: each critical event type is emitted for exactly
      one condition. Owned by `strangle-observability-gaps`; same treatment.
- [x] 4.4 Fix `tests/strategy/test_directional_strangle.py:953, 979, 1003, 1025` — they assert
      `POSITION_SIZE_CAPPED` **by name** while it is emitted for three unrelated conditions, so they
      pass no matter which one fired. Assert the condition, not the label.

## 5. Make green the gate
- [x] 5.1 `Taskfile.yml`: `test` exits non-zero on any failure (verified: already true, no change
      needed — `uv run pytest`'s exit code propagates through go-task by default; confirmed with a
      real failing test locally, exit 201, then reverted)
- [x] 5.2 CI check on push and PR (`.github/workflows/ci.yml` — backend pytest against real
      Postgres/Redis service containers, + flutter analyze/test)
- [x] 5.3 **Delete the "pre-existing debt" paragraph from `backend/CLAUDE.md`.** Its existence is
      what permitted the baseline to rot.
- [x] 5.4 `docs/RUNBOOK.md`: green is the definition of done

## 6. Dart lint sweep
- [x] 6.1 Fix the 7 `info` findings: `backtest_mock_source.dart:134`,
      `critical_alerts_card.dart:51`, `daily_pnl_tab.dart:202, 212, 432, 434, 608`
- [x] 6.2 `app/analysis_options.yaml`: fail on `info` (elevated the two violated rules to `error`;
      `task app:test` and CI also pass `--fatal-infos` as a second, blanket layer)
- [x] 6.3 `cd app` then `flutter analyze` → zero issues; `cd app` then `flutter test` → all pass
      (verified: "No issues found!"; 28/28 tests passing)

## 7. Explicitly out of scope
- [x] 7.1 The 267 ruff items. Record the count; fix them in a separate pass. Mixing a lint sweep into
      a test rescue makes the diff unreviewable. (Recorded in README: actual count is 646, not 267 —
      not fixed here.)

## 8. Validation
- [x] 8.1 `task test` green, exit code 0
- [x] 8.2 The inventory in the README shows every cluster as fixed or strict-xfailed with an owner
- [x] 8.3 `openspec validate --strict test-suite-baseline-green` passes (verified: "Change
      'test-suite-baseline-green' is valid")
