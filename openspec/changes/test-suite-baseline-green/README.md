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
