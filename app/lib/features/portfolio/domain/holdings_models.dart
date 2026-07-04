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
