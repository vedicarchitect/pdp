import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdp_app/features/dashboard/application/dashboard_providers.dart';
import 'package:pdp_app/features/dashboard/data/dashboard_source.dart';
import 'package:pdp_app/features/dashboard/data/watchlist_repository.dart';
import 'package:pdp_app/features/dashboard/domain/dashboard_models.dart';
import 'package:pdp_app/features/dashboard/presentation/dashboard_screen.dart';
import 'package:pdp_app/features/portfolio/domain/portfolio_summary.dart';

class _FixedDashboardSource implements DashboardSource {
  _FixedDashboardSource(this.data);
  final DashboardData data;

  @override
  Stream<DashboardData> streamDashboard() => Stream.value(data);
}

const _baseData = DashboardData(
  indices: [
    MarketIndex(securityId: '13', name: 'NIFTY', available: true, ltp: 24700.0, prevClose: 24600.0),
    MarketIndex(securityId: '25', name: 'BANKNIFTY', available: false),
  ],
  summary: PortfolioSummary(
    totalUnrealizedPnl: 1000,
    totalRealizedPnl: 500,
    dayPnl: 1500,
    openPositions: 2,
    mode: 'paper',
  ),
);

Widget _wrap(DashboardData data, {WatchlistRepository? watchlistRepo}) {
  return ProviderScope(
    overrides: [
      dashboardSourceProvider.overrideWithValue(_FixedDashboardSource(data)),
      if (watchlistRepo != null) watchlistRepositoryProvider.overrideWithValue(watchlistRepo),
    ],
    child: const MaterialApp(home: Scaffold(body: DashboardScreen())),
  );
}

void main() {
  testWidgets('renders index cards with change computed vs prev_close', (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    expect(find.text('NIFTY'), findsWidgets); // index card label (watchlist chip shows a quote suffix)
    // 24700 - 24600 = +100 (0.41%) — vs-prev-close, not a running sum.
    expect(find.textContaining('+100.0'), findsOneWidget);
  });

  testWidgets('unavailable index renders as Unavailable, not fabricated', (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    expect(find.text('BANKNIFTY'), findsWidgets); // index card + watchlist chip
    expect(find.text('Unavailable'), findsWidgets);
  });

  testWidgets('FII/DII panel is hidden when unavailable', (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    expect(find.text('FII / DII Net Flow'), findsNothing);
  });

  testWidgets('FII/DII panel shows when available', (tester) async {
    const data = DashboardData(
      indices: [],
      summary: PortfolioSummary.empty,
      fiiDii: FiiDiiHistory(available: true, days: [
        FiiDiiDay(date: '2026-07-03', fiiNet: 1355.33, diiNet: -1953.89),
      ]),
    );
    await tester.pumpWidget(_wrap(data, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    expect(find.text('FII / DII Net Flow'), findsOneWidget);
    expect(find.text('2026-07-03'), findsOneWidget);
  });

  testWidgets('sentiment and news sections hidden when unavailable', (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    expect(find.text('Sentiment & News'), findsNothing);
  });

  testWidgets('watchlist add and remove persists via repository', (tester) async {
    final repo = InMemoryWatchlistRepository();
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: repo));
    await tester.pumpAndSettle();

    // Seeded with NIFTY, BANKNIFTY by InMemoryWatchlistRepository.
    expect(find.text('NIFTY'), findsWidgets);
    expect(find.text('BANKNIFTY'), findsWidgets);

    await tester.enterText(find.byType(TextField), 'SENSEX');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(find.text('SENSEX'), findsOneWidget);
    expect(await repo.load(), contains('SENSEX'));

    await tester.ensureVisible(find.text('SENSEX'));
    await tester.pumpAndSettle();

    final deleteIcon = find.descendant(
      of: find.widgetWithText(Chip, 'SENSEX'),
      matching: find.byIcon(Icons.cancel),
    );
    await tester.tap(deleteIcon);
    await tester.pumpAndSettle();

    expect(find.text('SENSEX'), findsNothing);
    expect(await repo.load(), isNot(contains('SENSEX')));
  });

  testWidgets('watchlist chip shows a live quote for a symbol on the index/LTP data path',
      (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    // NIFTY is seeded in the watchlist and priced in _baseData.indices (ltp 24700.0) — its
    // resolved quote should render alongside the chip label (the index card shows the same
    // LTP with a leading "+" sign, so match the chip's exact unsigned text).
    expect(find.text('NIFTY  ₹24,700.00'), findsOneWidget);
  });

  testWidgets('watchlist chip shows no quote for a symbol outside the priced data path',
      (tester) async {
    await tester.pumpWidget(_wrap(_baseData, watchlistRepo: InMemoryWatchlistRepository()));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'TCS');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    // TCS has no index/commodity quote to resolve — shown plain, never fabricated.
    expect(find.text('TCS'), findsOneWidget);
  });
}
