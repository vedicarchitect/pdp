import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pdp_app/features/manage/application/manage_providers.dart';
import 'package:pdp_app/features/manage/domain/broker_models.dart';
import 'package:pdp_app/features/manage/presentation/tabs/broker_tab.dart';

/// Broker (Dhan) tab renders holdings + open/closed positions + funds and a
/// staleness badge — the parallel view for manual broker rows.
void main() {
  BrokerAccount account({String? syncedAt}) => BrokerAccount(
        state: BrokerSyncState.ready,
        holdings: [
          BrokerHolding(
            securityId: '1',
            symbol: 'INFY',
            exchange: 'NSE',
            totalQty: 10,
            availableQty: 10,
            avgCostPrice: 1500,
            lastPrice: 1600,
            lastSyncedAt: syncedAt,
          ),
        ],
        positions: [
          BrokerPosition(
            securityId: '2',
            symbol: 'NIFTY-CE',
            exchangeSegment: 'NSE_FNO',
            netQty: -50,
            buyAvg: 0,
            sellAvg: 120,
            realizedPnl: 0,
            unrealizedPnl: -400,
            lastSyncedAt: syncedAt,
          ),
        ],
        fund: BrokerFund(
          availableBalance: 100000,
          utilizedAmount: 20000,
          collateralAmount: 0,
          withdrawableBalance: 80000,
          lastSyncedAt: syncedAt,
        ),
      );

  Future<void> pump(WidgetTester tester, BrokerAccount acct) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          brokerAccountProvider.overrideWith((ref) => Stream.value(acct)),
        ],
        child: const MaterialApp(home: Scaffold(body: BrokerTab())),
      ),
    );
    await tester.pump();
  }

  testWidgets('renders holdings, positions and funds', (tester) async {
    await pump(tester, account(syncedAt: DateTime.now().toIso8601String()));

    expect(find.text('INFY'), findsOneWidget);
    expect(find.text('NIFTY-CE'), findsOneWidget);
    expect(find.textContaining('Holdings (1)'), findsOneWidget);
    expect(find.textContaining('Positions — Open (1)'), findsOneWidget);
    expect(find.textContaining('Synced'), findsOneWidget);
  });

  testWidgets('shows a stale warning when never synced', (tester) async {
    await pump(tester, account(syncedAt: null));
    expect(find.textContaining('Never synced'), findsOneWidget);
  });

  // An empty account and a subsystem that never ran must not look the same.
  testWidgets('explains a disabled subsystem instead of showing an empty list', (tester) async {
    await pump(tester, const BrokerAccount(state: BrokerSyncState.disabled));
    expect(find.text('Broker sync is off'), findsOneWidget);
    expect(find.textContaining('no open broker positions'), findsNothing);
  });

  testWidgets('explains missing credentials', (tester) async {
    await pump(tester, const BrokerAccount(state: BrokerSyncState.noCredentials));
    expect(find.text('No Dhan credentials'), findsOneWidget);
  });

  testWidgets('explains an unsynced mirror', (tester) async {
    await pump(tester, const BrokerAccount(state: BrokerSyncState.neverSynced));
    expect(find.text('Waiting for first sync'), findsOneWidget);
  });

  testWidgets('a ready but flat account shows the normal empty sections', (tester) async {
    await pump(tester, const BrokerAccount(state: BrokerSyncState.ready));
    expect(find.textContaining('no open broker positions'), findsOneWidget);
    expect(find.text('Broker sync is off'), findsNothing);
  });
}
