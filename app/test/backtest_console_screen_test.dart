import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdp_app/features/backtest/application/backtest_providers.dart';
import 'package:pdp_app/features/backtest/data/backtest_mock_source.dart';
import 'package:pdp_app/features/backtest/data/backtest_source.dart';
import 'package:pdp_app/features/backtest/presentation/backtest_console_screen.dart';

void main() {
  Widget wrap(Widget child, {BacktestSource? source}) {
    return ProviderScope(
      overrides: [
        backtestSourceProvider.overrideWithValue(source ?? BacktestMockSource()),
      ],
      child: MaterialApp(home: child),
    );
  }

  testWidgets('renders seeded runs with verdict chips', (tester) async {
    await tester.pumpWidget(wrap(const BacktestConsoleScreen()));
    await tester.pumpAndSettle();

    expect(find.text('Backtest Console'), findsOneWidget);
    expect(find.textContaining('strangle_2026'), findsWidgets);
    expect(find.text('PASS'), findsWidgets);
    
    // Tap SENSEX tab to see the REVIEW run
    await tester.tap(find.text('SENSEX'));
    await tester.pumpAndSettle();
    expect(find.text('REVIEW'), findsOneWidget);
  });

  testWidgets('filtering by verdict narrows the runs table', (tester) async {
    await tester.pumpWidget(wrap(const BacktestConsoleScreen()));
    await tester.pumpAndSettle();

    // Tap SENSEX tab to see the REVIEW run
    await tester.tap(find.text('SENSEX'));
    await tester.pumpAndSettle();

    // Two PASS runs + one REVIEW run are seeded.
    expect(find.text('REVIEW'), findsOneWidget);

    await tester.tap(find.text('All verdicts'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('PASS').last);
    await tester.pumpAndSettle();

    expect(find.text('REVIEW'), findsNothing);
  });

  testWidgets('launching a single run shows live progress then appears in the table',
      (tester) async {
    await tester.pumpWidget(wrap(const BacktestConsoleScreen()));
    await tester.pumpAndSettle();

    final initialRunTiles = find.textContaining('strangle_2026');
    final initialCount = initialRunTiles.evaluate().length;

    await tester.tap(find.text('New Run'));
    await tester.pumpAndSettle();

    // Pick the first strategy from the registry dropdown.
    await tester.tap(find.byKey(const Key('strategyDropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('directional_strangle_nifty').last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Launch'));
    await tester.pumpAndSettle();

    // Progress view should show, then settle at 100% / Completed.
    expect(find.textContaining('%'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();

    expect(find.text('Done'), findsOneWidget);
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();

    final finalCount = find.textContaining('strangle_2026').evaluate().length +
        find.textContaining('strangle_1').evaluate().length;
    expect(finalCount, greaterThan(initialCount));
  });
}
