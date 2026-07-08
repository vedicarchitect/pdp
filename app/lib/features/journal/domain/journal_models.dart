import 'package:flutter/foundation.dart';

@immutable
class JournalDay {
  final String date;
  final List<JournalTrade> trades;
  final Map<String, List<JournalTrade>> byIndex;
  final JournalStats stats;
  final String notes;
  final List<String> tags;
  final List<String> screenshots;

  const JournalDay({
    required this.date,
    required this.trades,
    required this.stats,
    this.byIndex = const {},
    this.notes = '',
    this.tags = const [],
    this.screenshots = const [],
  });

  factory JournalDay.fromJson(Map<String, dynamic> json) {
    final Map<String, List<JournalTrade>> parsedByIndex = {};
    if (json['by_index'] != null) {
      final map = json['by_index'] as Map<String, dynamic>;
      for (final entry in map.entries) {
        final list = entry.value as List?;
        if (list != null) {
          parsedByIndex[entry.key] = list
              .map((e) => JournalTrade.fromJson(e as Map<String, dynamic>))
              .toList();
        }
      }
    }

    return JournalDay(
      date: json['date'] as String,
      trades: (json['trades'] as List?)
              ?.map((e) => JournalTrade.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      byIndex: parsedByIndex,
      // The old format gives us 'stats', the new format (from trade_ledger) gives us 'totals'
      stats: JournalStats.fromJson(
        json['stats'] as Map<String, dynamic>? ?? json['totals'] as Map<String, dynamic>? ?? {},
      ),
      notes: json['notes'] as String? ?? '',
      tags: (json['tags'] as List?)?.map((e) => e as String).toList() ?? [],
      screenshots:
          (json['screenshots'] as List?)?.map((e) => e as String).toList() ?? [],
    );
  }

  JournalDay copyWith({
    String? notes,
    List<String>? tags,
    List<String>? screenshots,
  }) {
    return JournalDay(
      date: date,
      trades: trades,
      byIndex: byIndex,
      stats: stats,
      notes: notes ?? this.notes,
      tags: tags ?? this.tags,
      screenshots: screenshots ?? this.screenshots,
    );
  }
}

@immutable
class JournalTrade {
  // Legacy raw-fill fields
  final String ts;
  final String securityId;
  final String side;
  final double qty;
  final double fillPrice;
  final double charges;
  final String? strategyId;

  // New round-trip ledger fields
  final String? underlying;
  final String? symbol;
  final String? optType;
  final double? strike;
  final String? expiry;
  final bool isHedge;
  final double? entryPrice;
  final String? entryTime;
  final double? exitPrice;
  final String? exitTime;
  final double? pnl;
  final String? reason;
  final bool partial;
  final bool open;

  const JournalTrade({
    required this.ts,
    required this.securityId,
    required this.side,
    required this.qty,
    required this.fillPrice,
    required this.charges,
    this.strategyId,
    this.underlying,
    this.symbol,
    this.optType,
    this.strike,
    this.expiry,
    this.isHedge = false,
    this.entryPrice,
    this.entryTime,
    this.exitPrice,
    this.exitTime,
    this.pnl,
    this.reason,
    this.partial = false,
    this.open = false,
  });

  factory JournalTrade.fromJson(Map<String, dynamic> json) {
    return JournalTrade(
      ts: json['ts'] as String? ?? '',
      securityId: json['security_id'] as String? ?? json['sid'] as String? ?? '',
      side: json['side'] as String? ?? '',
      qty: (json['qty'] as num?)?.toDouble() ?? (json['lots'] as num?)?.toDouble() ?? 0.0,
      fillPrice: double.tryParse(json['fill_price']?.toString() ?? '0') ?? 0.0,
      charges: double.tryParse(json['charges']?.toString() ?? '0') ?? 0.0,
      strategyId: json['strategy_id'] as String?,
      
      underlying: json['underlying'] as String?,
      symbol: json['symbol'] as String?,
      optType: json['opt_type'] as String?,
      strike: (json['strike'] as num?)?.toDouble(),
      expiry: json['expiry'] as String?,
      isHedge: json['is_hedge'] as bool? ?? false,
      entryPrice: (json['entry_price'] as num?)?.toDouble(),
      entryTime: json['entry_time'] as String?,
      exitPrice: (json['exit_price'] as num?)?.toDouble(),
      exitTime: json['exit_time'] as String?,
      pnl: (json['pnl'] as num?)?.toDouble(),
      reason: json['reason'] as String?,
      partial: json['partial'] as bool? ?? false,
      open: json['open'] as bool? ?? false,
    );
  }
}

@immutable
class JournalStats {
  final int totalTrades;
  final int sells;
  final int buys;
  final int securitiesTraded;
  final double grossPremiumSold;
  final double grossPremiumBought;
  final double netPremium;
  final double totalCharges;
  final double realizedPnl;
  final int roundTrips;
  final int wins;
  final int losses;
  final double winRate;

  const JournalStats({
    required this.totalTrades,
    required this.sells,
    required this.buys,
    required this.securitiesTraded,
    required this.grossPremiumSold,
    required this.grossPremiumBought,
    required this.netPremium,
    required this.totalCharges,
    required this.realizedPnl,
    required this.roundTrips,
    required this.wins,
    required this.losses,
    required this.winRate,
  });

  factory JournalStats.fromJson(Map<String, dynamic> json) {
    return JournalStats(
      totalTrades: json['total_trades'] as int? ?? 0,
      sells: json['sells'] as int? ?? 0,
      buys: json['buys'] as int? ?? 0,
      securitiesTraded: json['securities_traded'] as int? ?? 0,
      grossPremiumSold: (json['gross_premium_sold'] as num?)?.toDouble() ?? 0.0,
      grossPremiumBought:
          (json['gross_premium_bought'] as num?)?.toDouble() ?? 0.0,
      netPremium: (json['net_premium'] as num?)?.toDouble() ?? 0.0,
      totalCharges: (json['total_charges'] as num?)?.toDouble() ?? 0.0,
      realizedPnl: (json['realized_pnl'] as num?)?.toDouble() ?? 0.0,
      roundTrips: json['round_trips'] as int? ?? 0,
      wins: json['wins'] as int? ?? 0,
      losses: json['losses'] as int? ?? 0,
      winRate: (json['win_rate'] as num?)?.toDouble() ?? 0.0,
    );
  }
}
