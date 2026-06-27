/// Headline portfolio totals. Mirrors `GET /api/v1/portfolio/summary`.
class PortfolioSummary {
  const PortfolioSummary({
    required this.totalUnrealizedPnl,
    required this.totalRealizedPnl,
    required this.dayPnl,
    required this.openPositions,
    required this.mode,
  });

  final double totalUnrealizedPnl;
  final double totalRealizedPnl;
  final double dayPnl;
  final int openPositions;

  /// `'paper'` or `'live'`.
  final String mode;

  static const PortfolioSummary empty = PortfolioSummary(
    totalUnrealizedPnl: 0,
    totalRealizedPnl: 0,
    dayPnl: 0,
    openPositions: 0,
    mode: 'paper',
  );

  factory PortfolioSummary.fromJson(Map<String, dynamic> json) {
    final unreal = _asDouble(json['total_unrealized_pnl']);
    final real = _asDouble(json['total_realized_pnl']);
    return PortfolioSummary(
      totalUnrealizedPnl: unreal,
      totalRealizedPnl: real,
      dayPnl: json.containsKey('day_pnl') ? _asDouble(json['day_pnl']) : unreal + real,
      openPositions: _asInt(json['open_positions']),
      mode: '${json['mode'] ?? 'paper'}',
    );
  }
}

double _asDouble(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? 0;
  return 0;
}

int _asInt(Object? v) {
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? 0;
  return 0;
}
