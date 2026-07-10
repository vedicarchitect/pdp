# test-suite-baseline-green

## Why

`task test` does not pass, and it has not passed for long enough that the project documents the
failures as furniture. `backend/CLAUDE.md` says:

> `task lint`/`task test` carry **pre-existing** debt (267 ruff items, 27 test failures e.g.
> `PositionState` needing `strategy_id`) unrelated to layout — clean up in a dedicated change.

The most recent full run in this working tree was **45 failed / 948 passed**. The documented figure
is 27. Nobody knows which is right, because "green" stopped being the definition of done. That is the
actual defect here: **a red baseline cannot detect a new regression.** Every change in the current
sequence — five of which touch the strategy that lost money on 2026-07-09 — will be validated against
a suite whose failures are, by convention, ignored.

The failures are not evenly distributed. The largest cluster is `tests/risk/test_loss_cap.py`, where
**all 11 tests fail** with `TypeError: PositionState.__init__() missing 1 required positional
argument: 'strategy_id'`. That file tests `KillSwitchService` and the hard day-loss cap — the
mechanism that is supposed to halt trading when losses breach a limit.

On 2026-07-08 that exact mechanism fired on phantom P&L: a leg stored with `entry_price=0` produced a
fabricated `-2.3L` day loss and halted BANKNIFTY for the session. The tests that would exercise the
cap's behaviour have been failing to even construct their fixtures. A safety mechanism whose test
file does not run is not a tested safety mechanism.

Three secondary observations, each of which the tests should have caught and did not:

- `pdp/orders/command_channel.py` imported `OrderRequest` from a module that never defined it,
  killing `WebGroup` and `FeedEngineGroup` on every boot for weeks. No test asserted that the runtime
  groups start.
- `_rehydrate_legs` reads a Mongo collection nothing writes (`strangle-leg-state-durability`). No
  test asserted a leg survives a restart.
- `POSITION_SIZE_CAPPED` is asserted **by name** in four tests
  (`tests/strategy/test_directional_strangle.py:953, 979, 1003, 1025`) while being emitted for three
  unrelated conditions. The assertions pass regardless of which condition fired.

These are the same shape: the suite tests that code runs, not that the system holds its invariants.

`flutter analyze` is comparatively healthy — 7 issues, all severity `info`, all in
`daily_pnl_tab.dart`, `critical_alerts_card.dart` and `backtest_mock_source.dart`. `flutter test`
passes 28/28. The Dart side needs a lint sweep, not a rescue.

## What Changes

- **Measure the real baseline once, precisely.** Record the exact failure count, the failing node ids,
  and a one-line cause per cluster. Commit that inventory into this change. Until it exists, "45 vs
  27" is a guess and progress cannot be measured.

- **Fix `tests/risk/test_loss_cap.py` first, and treat it as a bug in the tests *or* the code.**
  `PositionState` gained a required `strategy_id`; the fixtures never followed. Determine whether the
  production signature change was correct. If it was, update the fixtures. If it was not — if
  `strategy_id` should have a default — the failing tests are reporting a real API regression and the
  fix belongs in `pdp/portfolio/`.

- **Then the rest, cluster by cluster, in descending size.** Each cluster is either fixed, or
  quarantined with `@pytest.mark.xfail(strict=True, reason=...)` naming the change that will fix it.
  `strict=True` matters: an xfail that starts passing must fail the suite, or the quarantine becomes
  a graveyard.

- **Make green the gate.** Once the suite is green, `task test` fails the build on any failure. Add a
  CI check so the baseline cannot silently rot again. Delete the "pre-existing debt" paragraph from
  `backend/CLAUDE.md` — its existence is what permitted the rot.

- **Add the three invariant tests whose absence let real bugs ship.** Runtime groups start (all
  `required = True` groups construct); a leg survives a restart with its type intact; each critical
  event type is emitted for exactly one condition. These are not coverage padding — each one maps to
  a defect that reached live trading.

- **Sweep the Dart lints.** 7 `info` items, zero errors. Fix them and set `flutter analyze` to fail on
  `info` so the count stays at zero.

- **Leave the 267 ruff items to a separate pass.** Lint and test are different problems and mixing
  them makes the diff unreviewable. Record the count; do not fix it here.

## Impact

- **Affected specs:** `test-suite-baseline-green` (new).
- **Affected code:** `backend/tests/**` (fixtures), possibly `backend/pdp/portfolio/` (if the
  `PositionState` signature is the real defect), `backend/pdp/runtime/groups.py` (startup test),
  `Taskfile.yml` (`test` fails on failure), `backend/CLAUDE.md` (delete the debt paragraph),
  `app/analysis_options.yaml`, CI config.
- **Sequencing: land this early, but not first.** `dev-reload-scoping` comes before it — you cannot
  iterate on tests while the backend restarts under you. After that, a green baseline makes every
  subsequent change in the sequence verifiable. Landing the strategy fixes against a red suite means
  their regression tests prove nothing about the rest of the system.
- **This change may find real bugs.** A test that has been failing for months is an unread bug report.
  Budget for the possibility that some of the 45 are correct and the production code is wrong —
  particularly in `test_loss_cap.py`, which guards a safety mechanism that has already misfired in
  production.
- **No runtime behaviour changes** unless task 2 concludes the production signature was wrong. Ties
  into [[dead_command_channel_import]], [[execution_daily_parity]],
  [[leg_rehydration_misclassification_bug]].
