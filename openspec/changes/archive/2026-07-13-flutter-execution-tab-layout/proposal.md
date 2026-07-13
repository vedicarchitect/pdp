# flutter-execution-tab-layout

## Why

The execution monitor tab crashed on the Windows desktop app with `Vertical viewport was given
unbounded height`, followed by roughly twenty cascading `RenderBox was not laid out`,
`'child.hasSize': is not true` and `Null check operator used on a null value` exceptions. The tab
rendered nothing.

`_PositionsBody` (`app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart`) chooses
between two layouts at a 900px breakpoint. The wide branch puts the positions column inside an
`Expanded` within a `Row`, which bounds its height. The narrow branch stacks the positions column and
the indicator panel inside an outer `ListView`. But `_PositionsColumn` **is itself a `ListView`**, so
in the narrow branch a vertical viewport is handed an unbounded height constraint —
`BoxConstraints(w=821.5, 0.0<=h<=Infinity)` — and the assertion fires. Every subsequent exception is
fallout from that one failed layout.

The reason a *desktop* window hit the *narrow* branch is the width in that constraint: **821.5px**,
below the 900px breakpoint. Nothing about the bug is phone-specific; any window narrower than 900px
triggers it, and the crash was reachable on every platform.

Writing the regression test for that bug exposed a **second, independent defect** that had not been
reported. `_IndexPriceRow` lays out NIFTY, BANKNIFTY and SENSEX as three equal-share `Expanded`
cells. At 500px each cell gets roughly 149px, while `"BANKNIFTY  52100.00"` needs about 200px, so the
row overflows — `A RenderFlex overflowed by 52 pixels on the right`, and 102px for the next cell. The
user's 821.5px window was wide enough to hide this, but the app targets Android, where **every phone
would have shown it**.

Both defects share a cause worth naming: the tab had no widget test that pumped it at a narrow
viewport. `broker_tab_test.dart` establishes the `ProviderScope`-override pattern for this feature
slice; the execution tab simply never used it. A layout that is only ever exercised at the developer's
window size is not exercised.

## What Changes

- **Bound the nested viewport.** `_PositionsColumn` takes a `nested` flag, set only by the narrow
  branch. When set it shrink-wraps and uses `NeverScrollableScrollPhysics`, leaving the outer
  `ListView` as the sole scrollable. The section count is small, so shrink-wrapping costs nothing
  here. The wide branch is unchanged — `Expanded` already bounds it.

- **Scale the index strip instead of overflowing it.** `_IndexPriceRow`'s inner `Row` is wrapped in
  `FittedBox(fit: BoxFit.scaleDown)`. Scaling is chosen over `TextOverflow.ellipsis` deliberately:
  ellipsizing would render `"BANK…"`, and the index name is the one thing in that cell that must stay
  readable.

- **Test the tab at both viewports.** `app/test/strategy_execution_tab_test.dart` pumps the real
  `StrategyExecutionTab` through `ProviderScope` overrides at 500×900 and 1400×900, with legs and
  with an empty position list, asserting `tester.takeException()` is null in each. Both narrow tests
  fail on the pre-fix code; the wide test passes. That asymmetry is the point — it is what a
  breakpoint bug looks like in a test suite.

- **Make the viewport test a convention.** Any presentation widget that branches on a width
  breakpoint gets a test at a viewport on each side of it. Recorded in `app/CLAUDE.md`.

## Impact

- **Affected specs:** `flutter-execution-tab-layout` (new). Amends
  `openspec/specs/intraday-monitor/spec.md`.
- **Affected code:** `app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart`
  (`_PositionsBody.build`, `_PositionsColumn`, `_IndexPriceRow`),
  `app/test/strategy_execution_tab_test.dart` (new), `app/CLAUDE.md`.
- **Already implemented, ahead of the spec.** This was fixed in response to a live crash report
  before the proposal existed, which inverts non-negotiable #1 (spec-first). The proposal is written
  retroactively so the capability is recorded and the convention is captured. It is called out rather
  than quietly backfilled.
- **Verified:** `flutter analyze` reports 0 errors (7 pre-existing `info` lints, all in files this
  change does not touch — `daily_pnl_tab.dart`, `critical_alerts_card.dart`,
  `backtest_mock_source.dart`). `flutter test` passes 28, up from 25.
- **No backend impact.** No API, schema or strategy behaviour changes.
- **Independent of the strategy sequence.** Can land in its own commit at any time; it does not belong
  in the `broker-sync-visibility` commit, whose scope is the broker mirror. Ties into [[flutter_app]].
