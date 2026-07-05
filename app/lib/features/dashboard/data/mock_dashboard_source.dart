import 'dart:async';
import 'dart:math';

import '../../portfolio/domain/portfolio_summary.dart';
import '../domain/dashboard_models.dart';
import 'dashboard_source.dart';

class MockDashboardSource implements DashboardSource {
  @override
  Stream<DashboardData> streamDashboard() async* {
    final rand = Random();

    List<MarketIndex> indices = const [
      MarketIndex(securityId: '13', name: 'NIFTY', available: true, ltp: 24700.0, prevClose: 24600.0),
      MarketIndex(securityId: '25', name: 'BANKNIFTY', available: true, ltp: 55800.0, prevClose: 55950.0),
      MarketIndex(securityId: '51', name: 'SENSEX', available: true, ltp: 81200.0, prevClose: 81050.0),
    ];

    var data = DashboardData(
      indices: indices,
      summary: const PortfolioSummary(
        totalUnrealizedPnl: 12500.0,
        totalRealizedPnl: 8300.0,
        dayPnl: 20800.0,
        openPositions: 4,
        mode: 'mock',
      ),
      globalIndices: const [
        GlobalIndexQuote(symbol: 'DOW', close: 52900.07, change: 320.5, changePct: 0.61),
        GlobalIndexQuote(symbol: 'NASDAQ', close: 25832.67, change: -85.2, changePct: -0.33),
        GlobalIndexQuote(symbol: 'SPX', close: 7483.24, change: 12.1, changePct: 0.16),
        GlobalIndexQuote(symbol: 'NIKKEI', close: 69744.07, change: 1104.5, changePct: 1.61),
        GlobalIndexQuote(symbol: 'HANGSENG', close: 23350.03, change: -180.4, changePct: -0.77),
        GlobalIndexQuote(symbol: 'FTSE', close: 10679.0, change: 25.3, changePct: 0.24),
      ],
      globalIndicesAvailable: true,
      commodities: const [
        CommodityQuote(symbol: 'GOLD', name: 'Gold', available: true, securityId: 'mock-gold', ltp: 72500.0),
        CommodityQuote(symbol: 'SILVER', name: 'Silver', available: true, securityId: 'mock-silver', ltp: 91200.0),
        CommodityQuote(symbol: 'CRUDE', name: 'Crude Oil', available: true, securityId: 'mock-crude', ltp: 6540.0),
        CommodityQuote(symbol: 'NATGAS', name: 'Natural Gas', available: true, securityId: 'mock-natgas', ltp: 210.5),
      ],
      vix: const VixData(available: true, securityId: '21', value: 13.4),
      nextExpiry: const NextExpiry(
        available: true,
        expiries: {'NIFTY': '2026-07-08', 'BANKNIFTY': '2026-07-09', 'SENSEX': '2026-07-10'},
      ),
      fiiDii: const FiiDiiHistory(available: true, days: [
        FiiDiiDay(date: '2026-07-03', fiiNet: 1355.33, diiNet: -1953.89),
        FiiDiiDay(date: '2026-07-02', fiiNet: -820.10, diiNet: 640.25),
        FiiDiiDay(date: '2026-07-01', fiiNet: 2100.0, diiNet: -900.5),
      ]),
      news: const NewsFeed(available: true, articles: [
        NewsArticle(headline: 'Markets rally as Nifty hits record high on strong earnings', source: 'Moneycontrol', url: ''),
        NewsArticle(headline: 'RBI holds rates steady, signals cautious optimism', source: 'Economic Times', url: ''),
      ]),
      sentiment: const SentimentData(available: true, blendedScore: 64.0, label: 'Bullish', newsScore: 68.0, internalsScore: 60.0),
      todayPnl: const TodayPnl(available: true, realizedPnl: 8300.0, roundTrips: 6, winRate: 0.6667),
      margin: const MarginSnapshot(available: true, availableBalance: 185000.0, utilizedAmount: 65000.0),
      strategies: const StrategyChips(available: true, strategies: [
        StrategyChip(id: 'directional_strangle_nifty', underlying: 'NIFTY', status: 'RUNNING'),
        StrategyChip(id: 'directional_strangle_banknifty', underlying: 'BANKNIFTY', status: 'RUNNING'),
        StrategyChip(id: 'directional_strangle_sensex', underlying: 'SENSEX', status: 'STOPPED'),
      ]),
    );

    yield data;

    while (true) {
      await Future.delayed(const Duration(seconds: 1));

      indices = data.indices.map((idx) {
        final delta = (rand.nextDouble() - 0.5) * 10;
        final newLtp = idx.ltp + delta;
        final spark = [...idx.sparkline, newLtp];
        if (spark.length > 30) spark.removeAt(0);
        return idx.copyWith(ltp: newLtp, sparkline: spark);
      }).toList();

      data = data.copyWith(
        indices: indices,
        summary: PortfolioSummary(
          totalUnrealizedPnl: (rand.nextDouble() - 0.2) * 50000,
          totalRealizedPnl: 8300.0,
          dayPnl: (rand.nextDouble() - 0.2) * 55000,
          openPositions: 4,
          mode: 'mock',
        ),
      );

      yield data;
    }
  }
}
