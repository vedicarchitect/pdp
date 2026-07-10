import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pdp_app/features/manage/application/manage_providers.dart';
import 'package:pdp_app/features/manage/domain/execution_models.dart';
import 'package:pdp_app/features/manage/presentation/tabs/strategy_execution_tab.dart';

/// The execution monitor stacks the indicator panel under the positions below
/// 900px. The positions column is itself a `ListView`, so the narrow layout
/// nests one scrollable inside another and must shrink-wrap the inner one —
/// otherwise the viewport is handed an unbounded height and the subtree fails
/// to lay out.
void main() {
  MonitorSnapshot snapshot({bool withLegs = true}) => MonitorSnapshot(
        indices: const [
          IndexPrice(name: 'NIFTY', spot: 24150.5, future: 24160.0),
          IndexPrice(name: 'BANKNIFTY', spot: 52100.0),
        ],
        groups: [
          if (withLegs)
            const UnderlyingGroup(
              underlying: 'NIFTY',
              legs: [
                LegRow(
                  securityId: '101',
                  optType: 'CE',
                  strike: 24300,
                  lots: 2,
                  entryPrice: 85.5,
                  ltp: 70.0,
                  mtm: 1162.5,
                  isHedge: false,
                  isMomentum: false,
                ),
                LegRow(
                  securityId: '102',
                  optType: 'PE',
                  strike: 24000,
                  lots: 2,
                  entryPrice: 78.0,
                  ltp: 90.0,
                  mtm: -900.0,
                  isHedge: false,
                  isMomentum: false,
                ),
              ],
              dayPnl: 262.5,
              bucket: 'neutral',
              doneForDay: false,
            ),
        ],
        dayRealized: 0,
        dayUnrealized: 262.5,
        dayPnl: 262.5,
        bucket: 'neutral',
        doneForDay: false,
        nOpenShorts: 2,
        nOpenHedges: 0,
        nOpenMomentum: 0,
        recentEvents: const [],
        indicators: const {},
      );

  const trades = StrangleTrades(date: '2026-07-10', byIndex: {});

  Future<void> pumpAt(
    WidgetTester tester,
    Size size, {
    required MonitorSnapshot snap,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          monitorStreamProvider.overrideWith((ref) => Stream.value(snap)),
          strangleTradesProvider.overrideWith((ref, date) => trades),
        ],
        child: const MaterialApp(
          home: Scaffold(body: StrategyExecutionTab()),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('narrow layout lays out without an unbounded-height viewport',
      (tester) async {
    await pumpAt(tester, const Size(500, 900), snap: snapshot());

    expect(tester.takeException(), isNull);
    expect(find.text('NIFTY'), findsWidgets);
  });

  testWidgets('narrow layout survives an empty position list', (tester) async {
    await pumpAt(tester, const Size(500, 900), snap: snapshot(withLegs: false));

    expect(tester.takeException(), isNull);
    expect(find.text('No positions today'), findsOneWidget);
  });

  testWidgets('wide layout docks the indicator panel beside the positions',
      (tester) async {
    await pumpAt(tester, const Size(1400, 900), snap: snapshot());

    expect(tester.takeException(), isNull);
    expect(find.text('NIFTY'), findsWidgets);
  });
}
