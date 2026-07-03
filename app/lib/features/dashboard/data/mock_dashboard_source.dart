import 'dart:async';
import 'dart:math';

import '../../portfolio/domain/portfolio_summary.dart';
import '../domain/dashboard_models.dart';
import 'dashboard_source.dart';

class MockDashboardSource implements DashboardSource {
  @override
  Stream<DashboardData> streamDashboard() async* {
    final rand = Random();
    
    List<MarketIndex> indices = [
      const MarketIndex(securityId: '13', name: 'NIFTY', ltp: 21500.0, change: 45.0, changePct: 0.21),
      const MarketIndex(securityId: '25', name: 'BANKNIFTY', ltp: 47800.0, change: -120.0, changePct: -0.25),
      const MarketIndex(securityId: '51', name: 'SENSEX', ltp: 71200.0, change: 150.0, changePct: 0.21),
    ];

    while (true) {
      await Future.delayed(const Duration(seconds: 1));
      
      indices = indices.map((idx) {
        final changeDelta = (rand.nextDouble() - 0.5) * 10;
        final newLtp = idx.ltp + changeDelta;
        final newChange = idx.change + changeDelta;
        final newChangePct = (newChange / (idx.ltp - idx.change)) * 100;
        return idx.copyWith(ltp: newLtp, change: newChange, changePct: newChangePct);
      }).toList();

      yield DashboardData(
        indices: indices,
        summary: PortfolioSummary(
          totalUnrealizedPnl: (rand.nextDouble() - 0.2) * 50000,
          totalRealizedPnl: 15000.0,
          dayPnl: (rand.nextDouble() - 0.2) * 65000,
          openPositions: 4,
          mode: 'mock',
        ),
      );
    }
  }
}
