import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdp_app/features/backtest/application/backtest_providers.dart';
import 'package:pdp_app/features/backtest/data/backtest_mock_source.dart';
import 'package:pdp_app/features/backtest/presentation/backtest_detail_screen.dart';

void main() {
  Widget wrap(Widget child) {
    return ProviderScope(
      overrides: [backtestSourceProvider.overrideWithValue(BacktestMockSource())],
      child: MaterialApp(home: child),
    );
  }

  testWidgets('single run shows Overview/Days/Decisions/Paper tabs, no Folds', (tester) async {
    await tester.pumpWidget(wrap(const BacktestDetailScreen(runId: 'strangle_20260701-093000')));
    await tester.pumpAndSettle();

    expect(find.text('Overview'), findsOneWidget);
    expect(find.text('Days'), findsOneWidget);
    expect(find.text('Decisions'), findsOneWidget);
    expect(find.text('Paper'), findsOneWidget);
    expect(find.text('Folds'), findsNothing);
    expect(find.text('Metrics'), findsOneWidget);
    expect(find.text('Equity'), findsOneWidget);
  });

  testWidgets('walkforward run shows a Folds tab with stitched-OOS verdict', (tester) async {
    await tester.pumpWidget(wrap(const BacktestDetailScreen(runId: 'strangle_20260702-101500')));
    await tester.pumpAndSettle();

    expect(find.text('Folds'), findsOneWidget);

    await tester.tap(find.text('Folds'));
    await tester.pumpAndSettle();

    expect(find.text('PASS'), findsWidgets);
    expect(find.textContaining('positive folds'), findsOneWidget);
  });

  testWidgets('promote button opens rationale dialog for a PASS un-promoted run', (tester) async {
    await tester.pumpWidget(wrap(const BacktestDetailScreen(runId: 'strangle_20260702-101500')));
    await tester.pumpAndSettle();

    expect(find.text('Promote'), findsOneWidget);
    await tester.tap(find.text('Promote'));
    await tester.pumpAndSettle();

    expect(find.text('Promote to paper'), findsOneWidget);
    expect(find.textContaining('Required thresholds'), findsOneWidget);
  });

  testWidgets('days tab expands to show trade fills', (tester) async {
    await tester.pumpWidget(wrap(const BacktestDetailScreen(runId: 'strangle_20260701-093000')));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Days'));
    await tester.pumpAndSettle();

    final firstExpansionTile = find.byType(ExpansionTile).first;
    await tester.tap(firstExpansionTile);
    await tester.pumpAndSettle();

    expect(find.text('entry'), findsWidgets);
  });
}
