class DailyLossStatus {
  final double netRealizedPnl;
  final double netUnrealizedPnl;
  final double netTotalPnl;
  final String status;
  final String lastUpdated;

  DailyLossStatus({
    required this.netRealizedPnl,
    required this.netUnrealizedPnl,
    required this.netTotalPnl,
    required this.status,
    required this.lastUpdated,
  });

  factory DailyLossStatus.fromJson(Map<String, dynamic> json) {
    return DailyLossStatus(
      netRealizedPnl: (json['net_realized_pnl'] as num?)?.toDouble() ?? 0.0,
      netUnrealizedPnl: (json['net_unrealized_pnl'] as num?)?.toDouble() ?? 0.0,
      netTotalPnl: (json['net_total_pnl'] as num?)?.toDouble() ?? 0.0,
      status: json['status'] as String? ?? '',
      lastUpdated: json['last_updated'] as String? ?? '',
    );
  }
}

class RiskSettings {
  final double riskDailyLossCapInr;
  final double riskPerStrategyLossCapInr;
  final double riskSoftCapPct;
  final double hardCapPct;
  final double strategyHardCapPct;

  RiskSettings({
    required this.riskDailyLossCapInr,
    required this.riskPerStrategyLossCapInr,
    required this.riskSoftCapPct,
    required this.hardCapPct,
    required this.strategyHardCapPct,
  });

  factory RiskSettings.fromJson(Map<String, dynamic> json) {
    return RiskSettings(
      riskDailyLossCapInr: (json['RISK_DAILY_LOSS_CAP_INR'] as num?)?.toDouble() ?? 0.0,
      riskPerStrategyLossCapInr: (json['RISK_PER_STRATEGY_LOSS_CAP_INR'] as num?)?.toDouble() ?? 0.0,
      riskSoftCapPct: (json['RISK_SOFT_CAP_PCT'] as num?)?.toDouble() ?? 0.0,
      hardCapPct: (json['hard_cap_pct'] as num?)?.toDouble() ?? 100.0,
      strategyHardCapPct: (json['strategy_hard_cap_pct'] as num?)?.toDouble() ?? 150.0,
    );
  }
}
