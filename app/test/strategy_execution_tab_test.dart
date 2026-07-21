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
  MonitorSnapshot snapshot({
    bool withLegs = true,
    MonitorReadiness readiness = MonitorReadiness.ok,
    Map<String, SidIndicators> indicators = const {},
    AtmOptionRow? atmCe,
    AtmOptionRow? atmPe,
    List<Map<String, dynamic>> recentEvents = const [],
    DateTime? asOf,
    List<IndexPrice>? indices,
    PremarketStatus premarket = PremarketStatus.unknown,
  }) =>
      MonitorSnapshot(
        asOf: asOf,
        indices: indices ??
            const [
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
                  dte: 3,
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
              dayRealized: 500.0,
              dayUnrealized: 262.5,
              dayPnl: 762.5,
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
        recentEvents: recentEvents,
        indicators: indicators,
        readiness: readiness,
        premarket: premarket,
        atmCe: atmCe,
        atmPe: atmPe,
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

  const blockedReadiness = MonitorReadiness(
    state: 'blocked',
    byUnderlying: {
      'NIFTY': StrategyReadinessRow(
        state: 'blocked',
        components: [
          ReadinessComponentRow(
            name: 'Reconciliation',
            state: 'blocked',
            reason: '1 leg(s) diverged',
          ),
        ],
      ),
    },
  );

  testWidgets('blocked readiness renders a chip at narrow width', (tester) async {
    await pumpAt(tester, const Size(500, 900), snap: snapshot(readiness: blockedReadiness));

    expect(tester.takeException(), isNull);
    expect(find.text('BLOCKED'), findsOneWidget);
  });

  testWidgets('blocked readiness renders a chip at wide width', (tester) async {
    await pumpAt(tester, const Size(1400, 900), snap: snapshot(readiness: blockedReadiness));

    expect(tester.takeException(), isNull);
    expect(find.text('BLOCKED'), findsOneWidget);
  });

  testWidgets('premarket banner shows when today\'s warmup job has not run',
      (tester) async {
    await pumpAt(tester, const Size(500, 900),
        snap: snapshot(premarket: const PremarketStatus(ranToday: false)));

    expect(tester.takeException(), isNull);
    expect(find.textContaining('Premarket warmup not run today'), findsOneWidget);
  });

  testWidgets('premarket banner hidden when the warmup job ran (and by default)',
      (tester) async {
    // Explicit ran-today…
    await pumpAt(tester, const Size(500, 900),
        snap: snapshot(premarket: const PremarketStatus(ranToday: true)));
    expect(find.textContaining('Premarket warmup not run today'), findsNothing);

    // …and the default (absent field / older backend) must not false-alarm.
    await pumpAt(tester, const Size(500, 900), snap: snapshot());
    expect(find.textContaining('Premarket warmup not run today'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ok readiness renders no chip', (tester) async {
    await pumpAt(tester, const Size(1400, 900), snap: snapshot());

    expect(tester.takeException(), isNull);
    expect(find.text('BLOCKED'), findsNothing);
    expect(find.text('DEGRADED'), findsNothing);
  });

  const nifty5mCam = {
    '13': SidIndicators(
      sid: '13',
      tf: {'5m': IndicatorCell(ema9: 24100, ema20: 24120)},
      camarillaDaily: CamarillaLevels(r4: 24266.36, s4: 24147.45),
    ),
  };

  testWidgets(
      'maximized window shows every matrix column incl. Camarilla, not clipped by a fixed width',
      (tester) async {
    // Regression for indicator-matrix-kite-parity: a hardcoded 440px side panel
    // clipped CamR4/CamS4 off-screen when the window was maximized. The panel
    // now scales with the available width, so on a wide/maximized window the
    // DataTable's own horizontal scroll isn't needed to reach the last columns.
    await pumpAt(
      tester,
      const Size(1920, 1080),
      snap: snapshot(indicators: nifty5mCam),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('CamR4'), findsOneWidget);
    expect(find.text('CamS4'), findsOneWidget);
    // camForTf maps both 5m and 15m to the same daily doc, so the value
    // legitimately repeats across those two rows — assert presence, not count.
    expect(find.text('24266'), findsWidgets);
    expect(find.text('24147'), findsWidgets);
  });

  testWidgets('narrow window still renders the indicator panel without exceptions',
      (tester) async {
    await pumpAt(
      tester,
      const Size(500, 900),
      snap: snapshot(indicators: nifty5mCam),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('CamR4'), findsOneWidget);
  });

  testWidgets('NIFTY ATM CE/PE rows render when present', (tester) async {
    const atmCe = AtmOptionRow(
      label: 'NIFTY 24050 CE',
      strike: 24050,
      expiry: '2026-07-17',
      securityId: '99999',
      tf: {'5m': IndicatorCell(ema9: 200)},
    );
    const atmPe = AtmOptionRow(
      label: 'NIFTY 24050 PE',
      strike: 24050,
      expiry: '2026-07-17',
      securityId: '88888',
      tf: {'5m': IndicatorCell(ema9: 180)},
    );

    await pumpAt(
      tester,
      const Size(1400, 900),
      snap: snapshot(atmCe: atmCe, atmPe: atmPe),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('NIFTY 24050 CE'), findsOneWidget);
    expect(find.text('NIFTY 24050 PE'), findsOneWidget);
  });

  group('recent activity strip', () {
    testWidgets('hidden when there are no events', (tester) async {
      await pumpAt(tester, const Size(1400, 900), snap: snapshot());

      expect(tester.takeException(), isNull);
      expect(find.text('Recent activity'), findsNothing);
    });

    testWidgets('entry_aborted renders with reason and a warning treatment',
        (tester) async {
      final events = [
        {
          'event_type': 'entry_aborted',
          'underlying': 'NIFTY',
          'reason': 'fill_unresolved',
          'ist_time': '2026-07-17T10:05:00+05:30',
        },
      ];

      await pumpAt(tester, const Size(1400, 900), snap: snapshot(recentEvents: events));

      expect(tester.takeException(), isNull);
      expect(find.text('Recent activity'), findsOneWidget);
      expect(find.textContaining('entry aborted'), findsOneWidget);
      expect(find.textContaining('fill_unresolved'), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
    });

    testWidgets('non-aborted events render without the warning icon',
        (tester) async {
      final events = [
        {
          'event_type': 'square_off',
          'underlying': 'BANKNIFTY',
          'reason': 'square_off',
          'ist_time': '2026-07-17T15:30:00+05:30',
        },
      ];

      await pumpAt(tester, const Size(1400, 900), snap: snapshot(recentEvents: events));

      expect(tester.takeException(), isNull);
      expect(find.textContaining('square off'), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_rounded), findsNothing);
    });

    testWidgets('shows at most 5 of many events', (tester) async {
      final events = List.generate(
        8,
        (i) => {
          'event_type': 'leg_status',
          'underlying': 'NIFTY',
          'ist_time': '2026-07-17T10:0$i:00+05:30',
        },
      );

      await pumpAt(tester, const Size(1400, 900), snap: snapshot(recentEvents: events));

      expect(tester.takeException(), isNull);
      expect(find.textContaining('leg status'), findsNWidgets(5));
    });
  });

  group('expiry/DTE + combined P&L (strangle-execution-expiry-and-combined-pnl)', () {
    testWidgets('leg DTE column renders at wide width', (tester) async {
      await pumpAt(tester, const Size(1400, 900), snap: snapshot());
      expect(tester.takeException(), isNull);
      expect(find.text('DTE'), findsOneWidget); // column header
      expect(find.text('3'), findsWidgets); // the CE leg's dte value
    });

    testWidgets('leg DTE column renders at narrow width', (tester) async {
      await pumpAt(tester, const Size(500, 900), snap: snapshot());
      expect(tester.takeException(), isNull);
      expect(find.text('DTE'), findsOneWidget);
    });

    testWidgets('group header shows a combined realized+unrealized breakdown',
        (tester) async {
      await pumpAt(tester, const Size(1400, 900), snap: snapshot());
      expect(tester.takeException(), isNull);
      // Breakdown line under the bold combined total: a "realized" / "unrealized"
      // label pair, each followed by a PnlText rendering the signed, ₹-formatted,
      // Indian-grouped amount (same formatter + coloring as the total above).
      expect(find.text('realized '), findsOneWidget);
      expect(find.textContaining('unrealized'), findsOneWidget);
      // dayRealized (500.0) is unique to the group breakdown row — the overall
      // snapshot total only has dayUnrealized/dayPnl at 262.5, so this alone
      // proves the row renders via formatInr()/PnlText.
      expect(find.text('+₹500.00'), findsOneWidget);
    });
  });

  group('freshness badge', () {
    testWidgets('no server timestamp and no live tick renders "feed stale"',
        (tester) async {
      await pumpAt(
        tester,
        const Size(1400, 900),
        snap: snapshot(
          indices: const [
            IndexPrice(name: 'NIFTY', spot: 24150.5),
            IndexPrice(name: 'BANKNIFTY', spot: 52100.0),
          ],
        ),
      );

      expect(tester.takeException(), isNull);
      expect(find.text('feed stale'), findsOneWidget);
      expect(find.byIcon(Icons.wifi_off), findsOneWidget);
    });

    testWidgets('a fresh as_of and a recent tick render as live', (tester) async {
      await pumpAt(
        tester,
        const Size(1400, 900),
        snap: snapshot(
          asOf: DateTime.now(),
          indices: const [
            IndexPrice(name: 'NIFTY', spot: 24150.5, spotAgeS: 1.0),
            IndexPrice(name: 'BANKNIFTY', spot: 52100.0, spotAgeS: 1.5),
          ],
        ),
      );

      expect(tester.takeException(), isNull);
      expect(find.textContaining('s ago'), findsOneWidget);
      expect(find.byIcon(Icons.wifi), findsOneWidget);
    });

    testWidgets('a stale as_of renders "feed stale" even if a tick exists',
        (tester) async {
      await pumpAt(
        tester,
        const Size(1400, 900),
        snap: snapshot(
          asOf: DateTime.now().subtract(const Duration(seconds: 30)),
          indices: const [
            IndexPrice(name: 'NIFTY', spot: 24150.5, spotAgeS: 1.0),
          ],
        ),
      );

      expect(tester.takeException(), isNull);
      expect(find.byIcon(Icons.wifi_off), findsOneWidget);
    });
  });
}
