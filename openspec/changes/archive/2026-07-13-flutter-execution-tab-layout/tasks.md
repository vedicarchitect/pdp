# Tasks — flutter-execution-tab-layout

> **Already implemented.** This proposal was written retroactively, after a live crash report, which
> inverts non-negotiable #1 (spec-first). Tasks 1–4 are checked because the code exists and is
> verified; they are recorded so the change can be validated and archived honestly.

## 1. Regression tests (written before the second fix, and found it)
- [x] 1.1 `app/test/strategy_execution_tab_test.dart`: pump the real `StrategyExecutionTab` through
      `ProviderScope` overrides — `monitorStreamProvider.overrideWith((ref) => Stream.value(snap))`,
      `strangleTradesProvider.overrideWith((ref, date) => trades)` — following the pattern in
      `app/test/broker_tab_test.dart`
- [x] 1.2 `narrow layout lays out without an unbounded-height viewport` at 500×900
- [x] 1.3 `narrow layout survives an empty position list` at 500×900, asserting `No positions today`
- [x] 1.4 `wide layout docks the indicator panel beside the positions` at 1400×900
- [x] 1.5 Each asserts `expect(tester.takeException(), isNull)`
- [x] 1.6 Set the viewport with `tester.view.physicalSize` + `devicePixelRatio = 1.0` and
      `addTearDown(tester.view.reset)`
- [x] 1.7 Confirm the two narrow tests fail on the pre-fix code and the wide test passes — the
      asymmetry is the signature of a breakpoint bug

## 2. Bound the nested viewport (the reported crash)
- [x] 2.1 `_PositionsColumn` gains a `nested` flag, defaulting `false`
- [x] 2.2 When `nested`: `shrinkWrap: true` and `physics: NeverScrollableScrollPhysics()`
- [x] 2.3 `_PositionsBody.build` constructs `_PositionsColumn` per branch rather than once outside
      `LayoutBuilder`, so the narrow branch can opt in
- [x] 2.4 The wide branch is unchanged — `Expanded` inside the `Row` already bounds it

## 3. Index strip overflow (found by test 1.2, not reported by the user)
- [x] 3.1 Wrap `_IndexPriceRow`'s inner `Row` in `FittedBox(fit: BoxFit.scaleDown)`
- [x] 3.2 Scale rather than ellipsize — `"BANK…"` is not an acceptable rendering of `BANKNIFTY`

## 4. Verification
- [x] 4.1 `cd app` then `flutter test test/strategy_execution_tab_test.dart` → 3 passed
- [x] 4.2 `cd app` then `flutter analyze` → 0 errors (7 pre-existing `info`, none in touched files)
- [x] 4.3 `cd app` then `flutter test` → 28 passed (was 25)

## 5. Remaining
- [x] 5.1 `app/CLAUDE.md`: record the convention — a widget branching on a width breakpoint gets a
      widget test at a viewport on each side of it
- [ ] 5.2 Manual check on an Android device or emulator at phone width, confirming the index strip
      scales and the tab scrolls as one surface — **not done**: no Android device/emulator available
      in this environment; needs a manual pass by whoever has one
- [x] 5.3 Audit the other tabs for the same nested-scrollable and fixed-share-`Expanded` patterns —
      done: `grep -rn "LayoutBuilder\|MediaQuery.*width\|constraints\.maxWidth" app/lib/features/`
      shows only `strategy_execution_tab.dart` and `app_shell.dart` branch on a width breakpoint.
      `app_shell.dart` swaps `Scaffold.body` wholesale (`NavigationRail` Row vs. plain `child`) and
      never nests a `ListView`/`SingleChildScrollView` inside another scrollable, so it doesn't share
      the bug shape. No other tab combines width-branching with nested scrollables today — no
      follow-up filed. (11 files use `ListView`/`SingleChildScrollView` generally; none pair it with
      a width breakpoint, so the specific defect class here is contained to this fix.)
- [x] 5.4 `broker-sync-visibility` was already committed and archived (2026-07-10) before this change's
      code landed — the two never shared a commit
- [x] 5.5 `openspec validate --strict flutter-execution-tab-layout` passes
