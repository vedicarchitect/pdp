# flutter-execution-tab-layout — minimal context

Read only these. **Code is already written and verified; only tasks 5.x remain.**

| File | Why |
|------|-----|
| `app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart` | `_PositionsBody`, `_PositionsColumn`, `_IndexPriceRow`, `_splitBreakpoint = 900.0` |
| `app/test/strategy_execution_tab_test.dart` | The three regression tests |
| `app/test/broker_tab_test.dart` | The `ProviderScope`-override pattern followed |
| `app/lib/features/manage/application/manage_providers.dart` | `monitorStreamProvider`, `strangleTradesProvider` — the two overrides |
| `app/CLAUDE.md` | Where the breakpoint-test convention gets recorded |

## Key facts established during investigation
- The crash constraint was `BoxConstraints(w=821.5, 0.0<=h<=Infinity)` — **821.5px is below the 900px
  breakpoint**, which is why a desktop window took the narrow branch. Nothing about the bug is
  phone-specific.
- `_PositionsColumn` is itself a `ListView`. The narrow branch nests it in another `ListView`'s
  `children`, so the inner viewport gets an unbounded height. The ~20 `RenderBox was not laid out` /
  `child.hasSize` / null-check exceptions after it are all fallout from that single failure.
- The wide branch was always safe: `Expanded` inside the `Row` bounds the height.
- **The `_IndexPriceRow` overflow was found by the new test, not by the user.** Three equal `Expanded`
  cells give ~149px each at 500px, but `"BANKNIFTY  52100.00"` needs ~200px → overflow of 52px, then
  102px. The 821.5px window hid it. The app targets Android; every phone would have shown it.
- Private widgets (`_PositionsBody`, `_PositionsColumn`, `_IndexPriceRow`) cannot be imported by a
  test — drive them through the public `StrategyExecutionTab` with `ProviderScope` overrides.
- Riverpod 2.6.1: `StreamProvider.autoDispose` → `overrideWith((ref) => Stream.value(x))`;
  `FutureProvider.autoDispose.family` → `overrideWith((ref, arg) => value)`.

## Related
`[[flutter_app]]`. Independent of the strategy sequence. Commit separately from
`broker-sync-visibility` — the two share no scope.
