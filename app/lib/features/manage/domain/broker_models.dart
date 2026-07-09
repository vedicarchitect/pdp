/// Domain models for the Broker (Dhan) tab — the broker's own view of the
/// account (holdings / positions / funds), sourced from `/api/v1/broker-sync/*`.
/// Money fields arrive as strings from the API and are parsed to doubles here.
library;

double? _toD(Object? v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

class BrokerHolding {
  final String securityId;
  final String? symbol;
  final String? exchange;
  final int totalQty;
  final int availableQty;
  final double avgCostPrice;
  final double? lastPrice;
  final String? lastSyncedAt;

  const BrokerHolding({
    required this.securityId,
    this.symbol,
    this.exchange,
    required this.totalQty,
    required this.availableQty,
    required this.avgCostPrice,
    this.lastPrice,
    this.lastSyncedAt,
  });

  double get investedValue => totalQty * avgCostPrice;
  double get currentValue => totalQty * (lastPrice ?? avgCostPrice);
  double get pnl => currentValue - investedValue;

  factory BrokerHolding.fromJson(Map<String, dynamic> json) => BrokerHolding(
        securityId: json['security_id'] as String? ?? '',
        symbol: json['symbol'] as String?,
        exchange: json['exchange'] as String?,
        totalQty: (json['total_qty'] as num?)?.toInt() ?? 0,
        availableQty: (json['available_qty'] as num?)?.toInt() ?? 0,
        avgCostPrice: _toD(json['avg_cost_price']) ?? 0.0,
        lastPrice: _toD(json['last_price']),
        lastSyncedAt: json['last_synced_at'] as String?,
      );
}

class BrokerPosition {
  final String securityId;
  final String? symbol;
  final String exchangeSegment;
  final String? productType;
  final int netQty;
  final double buyAvg;
  final double sellAvg;
  final double realizedPnl;
  final double unrealizedPnl;
  final String? lastSyncedAt;

  const BrokerPosition({
    required this.securityId,
    this.symbol,
    required this.exchangeSegment,
    this.productType,
    required this.netQty,
    required this.buyAvg,
    required this.sellAvg,
    required this.realizedPnl,
    required this.unrealizedPnl,
    this.lastSyncedAt,
  });

  bool get isOpen => netQty != 0;

  factory BrokerPosition.fromJson(Map<String, dynamic> json) => BrokerPosition(
        securityId: json['security_id'] as String? ?? '',
        symbol: json['symbol'] as String?,
        exchangeSegment: json['exchange_segment'] as String? ?? '',
        productType: json['product_type'] as String?,
        netQty: (json['net_qty'] as num?)?.toInt() ?? 0,
        buyAvg: _toD(json['buy_avg']) ?? 0.0,
        sellAvg: _toD(json['sell_avg']) ?? 0.0,
        realizedPnl: _toD(json['realized_pnl']) ?? 0.0,
        unrealizedPnl: _toD(json['unrealized_pnl']) ?? 0.0,
        lastSyncedAt: json['last_synced_at'] as String?,
      );
}

class BrokerFund {
  final double availableBalance;
  final double utilizedAmount;
  final double collateralAmount;
  final double withdrawableBalance;
  final String? lastSyncedAt;

  const BrokerFund({
    required this.availableBalance,
    required this.utilizedAmount,
    required this.collateralAmount,
    required this.withdrawableBalance,
    this.lastSyncedAt,
  });

  factory BrokerFund.fromJson(Map<String, dynamic> json) => BrokerFund(
        availableBalance: _toD(json['available_balance']) ?? 0.0,
        utilizedAmount: _toD(json['utilized_amount']) ?? 0.0,
        collateralAmount: _toD(json['collateral_amount']) ?? 0.0,
        withdrawableBalance: _toD(json['withdrawable_balance']) ?? 0.0,
        lastSyncedAt: json['last_synced_at'] as String?,
      );
}

/// Aggregate of the three broker reads for the Broker (Dhan) tab.
class BrokerAccount {
  final List<BrokerHolding> holdings;
  final List<BrokerPosition> positions;
  final BrokerFund? fund;

  const BrokerAccount({
    required this.holdings,
    required this.positions,
    this.fund,
  });

  /// The most recent sync timestamp across all three reads (for the stale badge).
  String? get lastSyncedAt {
    final stamps = <String>[
      for (final h in holdings) if (h.lastSyncedAt != null) h.lastSyncedAt!,
      for (final p in positions) if (p.lastSyncedAt != null) p.lastSyncedAt!,
      if (fund?.lastSyncedAt != null) fund!.lastSyncedAt!,
    ]..sort();
    return stamps.isEmpty ? null : stamps.last;
  }
}
