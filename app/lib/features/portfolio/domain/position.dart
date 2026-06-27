/// A single open position with its MTM P&L.
///
/// Backend (`GET /api/v1/portfolio/positions`) returns numeric money fields as
/// strings (`str(Decimal)`), so parsing is tolerant of both num and String.
class Position {
  const Position({
    required this.securityId,
    required this.exchangeSegment,
    required this.product,
    required this.netQty,
    required this.avgPrice,
    required this.realizedPnl,
    required this.unrealizedPnl,
    this.symbol,
  });

  final String securityId;
  final String exchangeSegment;
  final String product;
  final int netQty;
  final double avgPrice;
  final double realizedPnl;
  final double unrealizedPnl;

  /// Optional human-readable name (used by the mock feed); null for live data.
  final String? symbol;

  double get pnl => realizedPnl + unrealizedPnl;

  /// What the UI shows as the row title.
  String get displayName => symbol ?? '$securityId · $exchangeSegment';

  Position copyWith({double? unrealizedPnl, double? realizedPnl}) => Position(
        securityId: securityId,
        exchangeSegment: exchangeSegment,
        product: product,
        netQty: netQty,
        avgPrice: avgPrice,
        realizedPnl: realizedPnl ?? this.realizedPnl,
        unrealizedPnl: unrealizedPnl ?? this.unrealizedPnl,
        symbol: symbol,
      );

  factory Position.fromJson(Map<String, dynamic> json) => Position(
        securityId: '${json['security_id'] ?? ''}',
        exchangeSegment: '${json['exchange_segment'] ?? ''}',
        product: '${json['product'] ?? ''}',
        netQty: _asInt(json['net_qty']),
        avgPrice: _asDouble(json['avg_price']),
        realizedPnl: _asDouble(json['realized_pnl']),
        unrealizedPnl: _asDouble(json['unrealized_pnl']),
        symbol: json['symbol'] as String?,
      );
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
