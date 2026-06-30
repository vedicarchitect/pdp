import '../../portfolio/domain/portfolio_summary.dart';

class MarketIndex {
  const MarketIndex({
    required this.securityId,
    required this.name,
    required this.ltp,
    required this.change,
    required this.changePct,
  });

  final String securityId;
  final String name;
  final double ltp;
  final double change;
  final double changePct;

  bool get isUp => change >= 0;

  MarketIndex copyWith({
    double? ltp,
    double? change,
    double? changePct,
  }) {
    return MarketIndex(
      securityId: securityId,
      name: name,
      ltp: ltp ?? this.ltp,
      change: change ?? this.change,
      changePct: changePct ?? this.changePct,
    );
  }
}

class DashboardData {
  const DashboardData({
    required this.indices,
    required this.summary,
  });

  final List<MarketIndex> indices;
  final PortfolioSummary summary;

  static const DashboardData empty = DashboardData(
    indices: [],
    summary: PortfolioSummary.empty,
  );
}
