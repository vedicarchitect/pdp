class HoldingsSummary {
  final double totalInvested;
  final double totalCurrentValue;
  final double totalPnl;
  final double totalPnlPct;
  final int holdingsCount;
  final double cashAvailable;

  const HoldingsSummary({
    required this.totalInvested,
    required this.totalCurrentValue,
    required this.totalPnl,
    required this.totalPnlPct,
    required this.holdingsCount,
    required this.cashAvailable,
  });

  factory HoldingsSummary.fromJson(Map<String, dynamic> json) {
    return HoldingsSummary(
      totalInvested: (json['total_invested'] as num).toDouble(),
      totalCurrentValue: (json['total_current_value'] as num).toDouble(),
      totalPnl: (json['total_pnl'] as num).toDouble(),
      totalPnlPct: (json['total_pnl_pct'] as num).toDouble(),
      holdingsCount: json['holdings_count'] as int,
      cashAvailable: (json['cash_available'] as num).toDouble(),
    );
  }
}

class HoldingDetail {
  final String symbol;
  final String exchange;
  final String sector;
  final int qty;
  final double avgPrice;
  final double lastPrice;
  final double investedValue;
  final double currentValue;
  final double pnl;
  final double pnlPct;

  const HoldingDetail({
    required this.symbol,
    required this.exchange,
    required this.sector,
    required this.qty,
    required this.avgPrice,
    required this.lastPrice,
    required this.investedValue,
    required this.currentValue,
    required this.pnl,
    required this.pnlPct,
  });

  factory HoldingDetail.fromJson(Map<String, dynamic> json) {
    return HoldingDetail(
      symbol: json['symbol'] as String,
      exchange: json['exchange'] as String? ?? '',
      sector: json['sector'] as String? ?? 'Other',
      qty: json['qty'] as int,
      avgPrice: (json['avg_price'] as num).toDouble(),
      lastPrice: (json['last_price'] as num).toDouble(),
      investedValue: (json['invested_value'] as num).toDouble(),
      currentValue: (json['current_value'] as num).toDouble(),
      pnl: (json['pnl'] as num).toDouble(),
      pnlPct: (json['pnl_pct'] as num).toDouble(),
    );
  }
}

class PositionDetail {
  final String accountId;
  final String securityId;
  final String exchangeSegment;
  final String productType;
  final String symbol;
  final int netQty;
  final double buyAvg;
  final double sellAvg;
  final double realizedPnl;
  final double unrealizedPnl;
  final double ltp;

  const PositionDetail({
    required this.accountId,
    required this.securityId,
    required this.exchangeSegment,
    required this.productType,
    required this.symbol,
    required this.netQty,
    required this.buyAvg,
    required this.sellAvg,
    required this.realizedPnl,
    required this.unrealizedPnl,
    this.ltp = 0.0,
  });

  double get liveUnrealizedPnl {
    if (netQty == 0 || ltp == 0.0) return unrealizedPnl;
    if (netQty > 0) return (ltp - buyAvg) * netQty;
    return (sellAvg - ltp) * netQty.abs();
  }

  PositionDetail copyWith({
    double? ltp,
  }) {
    return PositionDetail(
      accountId: accountId,
      securityId: securityId,
      exchangeSegment: exchangeSegment,
      productType: productType,
      symbol: symbol,
      netQty: netQty,
      buyAvg: buyAvg,
      sellAvg: sellAvg,
      realizedPnl: realizedPnl,
      unrealizedPnl: unrealizedPnl,
      ltp: ltp ?? this.ltp,
    );
  }

  factory PositionDetail.fromJson(Map<String, dynamic> json) {
    return PositionDetail(
      accountId: json['account_id'] as String? ?? '',
      securityId: json['security_id'] as String? ?? '',
      exchangeSegment: json['exchange_segment'] as String? ?? '',
      productType: json['product_type'] as String? ?? '',
      symbol: json['symbol'] as String? ?? '',
      netQty: (json['net_qty'] as num?)?.toInt() ?? 0,
      buyAvg: double.tryParse(json['buy_avg']?.toString() ?? '0') ?? 0.0,
      sellAvg: double.tryParse(json['sell_avg']?.toString() ?? '0') ?? 0.0,
      realizedPnl: double.tryParse(json['realized_pnl']?.toString() ?? '0') ?? 0.0,
      unrealizedPnl: double.tryParse(json['unrealized_pnl']?.toString() ?? '0') ?? 0.0,
    );
  }
}

