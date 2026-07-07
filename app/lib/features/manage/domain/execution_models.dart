/// Domain models for the Strategy Execution Monitor tab.
library;

// ─── Index price row ─────────────────────────────────────────────────────────

class IndexPrice {
  final String name;
  final double spot;
  final double? future;

  const IndexPrice({
    required this.name,
    required this.spot,
    this.future,
  });

  factory IndexPrice.fromJson(String name, Map<String, dynamic> json) {
    return IndexPrice(
      name: name,
      spot: (json['spot'] as num?)?.toDouble() ?? 0.0,
      future: (json['future'] as num?)?.toDouble(),
    );
  }
}

// ─── Leg row ─────────────────────────────────────────────────────────────────

class LegRow {
  final String securityId;
  final String optType; // "CE" or "PE"
  final double strike;
  final int lots;
  final double entryPrice;
  final String? entryTime;
  final String? entryReason;
  final double? ltp;
  final double? mtm;
  final bool isHedge;
  final bool isMomentum;
  // Greeks
  final double? delta;
  final double? vega;
  final double? gamma;
  final double? theta;
  final int? oi;
  final double? pcr;
  final int? oiChangeDay;

  const LegRow({
    required this.securityId,
    required this.optType,
    required this.strike,
    required this.lots,
    required this.entryPrice,
    this.entryTime,
    this.entryReason,
    this.ltp,
    this.mtm,
    required this.isHedge,
    required this.isMomentum,
    this.delta,
    this.vega,
    this.gamma,
    this.theta,
    this.oi,
    this.pcr,
    this.oiChangeDay,
  });

  factory LegRow.fromJson(Map<String, dynamic> json) {
    return LegRow(
      securityId: json['security_id'] as String? ?? '',
      optType: json['opt_type'] as String? ?? '',
      strike: (json['strike'] as num?)?.toDouble() ?? 0.0,
      lots: (json['lots'] as num?)?.toInt() ?? 0,
      entryPrice: (json['entry_price'] as num?)?.toDouble() ?? 0.0,
      entryTime: json['entry_time'] as String?,
      entryReason: json['entry_reason'] as String?,
      ltp: (json['ltp'] as num?)?.toDouble(),
      mtm: (json['mtm'] as num?)?.toDouble(),
      isHedge: json['is_hedge'] as bool? ?? false,
      isMomentum: json['is_momentum'] as bool? ?? false,
      delta: (json['delta'] as num?)?.toDouble(),
      vega: (json['vega'] as num?)?.toDouble(),
      gamma: (json['gamma'] as num?)?.toDouble(),
      theta: (json['theta'] as num?)?.toDouble(),
      oi: (json['oi'] as num?)?.toInt(),
      pcr: (json['pcr'] as num?)?.toDouble(),
      oiChangeDay: (json['oi_change_day'] as num?)?.toInt(),
    );
  }
}

// ─── Indicator cell ───────────────────────────────────────────────────────────

class IndicatorCell {
  final double? ema9;
  final double? ema20;
  final double? ema50;
  final double? ema100;
  final double? ema200;
  final double? stVal;
  final String? stDir; // "up" | "down"
  final double? psar;
  final double? rsi;
  final double? rsiMa; // SMA(14) signal line — Kite "RSI 14 SMA 14"
  final double? vwap; // sourced from futures contract
  final double? vwma; // sourced from futures contract

  const IndicatorCell({
    this.ema9,
    this.ema20,
    this.ema50,
    this.ema100,
    this.ema200,
    this.stVal,
    this.stDir,
    this.psar,
    this.rsi,
    this.rsiMa,
    this.vwap,
    this.vwma,
  });

  factory IndicatorCell.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const IndicatorCell();
    return IndicatorCell(
      ema9: (json['ema9'] as num?)?.toDouble(),
      ema20: (json['ema20'] as num?)?.toDouble(),
      ema50: (json['ema50'] as num?)?.toDouble(),
      ema100: (json['ema100'] as num?)?.toDouble(),
      ema200: (json['ema200'] as num?)?.toDouble(),
      stVal: (json['st_val'] as num?)?.toDouble(),
      stDir: json['st_dir'] as String?,
      psar: (json['psar'] as num?)?.toDouble(),
      rsi: (json['rsi'] as num?)?.toDouble(),
      rsiMa: (json['rsi_ma'] as num?)?.toDouble(),
      vwap: (json['vwap'] as num?)?.toDouble(),
      vwma: (json['vwma'] as num?)?.toDouble(),
    );
  }
}

// ─── Camarilla levels ─────────────────────────────────────────────────────────

class CamarillaLevels {
  final double? pp, r3, r4, s3, s4;

  const CamarillaLevels({this.pp, this.r3, this.r4, this.s3, this.s4});

  factory CamarillaLevels.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const CamarillaLevels();
    return CamarillaLevels(
      pp: (json['pp'] as num?)?.toDouble(),
      r3: (json['r3'] as num?)?.toDouble(),
      r4: (json['r4'] as num?)?.toDouble(),
      s3: (json['s3'] as num?)?.toDouble(),
      s4: (json['s4'] as num?)?.toDouble(),
    );
  }
}

// ─── Per-SID indicator data ───────────────────────────────────────────────────

class SidIndicators {
  final String sid;
  final Map<String, IndicatorCell> tf; // timeframe → cell
  final CamarillaLevels? camarillaDaily;
  final CamarillaLevels? camarillaWeekly;
  final CamarillaLevels? camarillaMonthly;
  final double? pdh, pdl, pwh, pwl, pmh, pml;

  const SidIndicators({
    required this.sid,
    required this.tf,
    this.camarillaDaily,
    this.camarillaWeekly,
    this.camarillaMonthly,
    this.pdh,
    this.pdl,
    this.pwh,
    this.pwl,
    this.pmh,
    this.pml,
  });

  /// Camarilla set for a timeframe: 5m/15m → daily, 30m/1H → weekly, 1D → monthly.
  CamarillaLevels? camForTf(String tf) {
    switch (tf) {
      case '5m':
      case '15m':
        return camarillaDaily;
      case '30m':
      case '1H':
        return camarillaWeekly;
      case '1D':
        return camarillaMonthly;
      default:
        return camarillaDaily;
    }
  }

  factory SidIndicators.fromJson(String sid, Map<String, dynamic> json) {
    final tfRaw = json['tf'] as Map<String, dynamic>? ?? {};
    final tf = tfRaw.map(
      (k, v) => MapEntry(k, IndicatorCell.fromJson(v as Map<String, dynamic>?)),
    );
    final period = json['period'] as Map<String, dynamic>?;
    return SidIndicators(
      sid: sid,
      tf: tf,
      camarillaDaily: CamarillaLevels.fromJson(
        json['camarilla_daily'] as Map<String, dynamic>?,
      ),
      camarillaWeekly: CamarillaLevels.fromJson(
        json['camarilla_weekly'] as Map<String, dynamic>?,
      ),
      camarillaMonthly: CamarillaLevels.fromJson(
        json['camarilla_monthly'] as Map<String, dynamic>?,
      ),
      pdh: (period?['pdh'] as num?)?.toDouble(),
      pdl: (period?['pdl'] as num?)?.toDouble(),
      pwh: (period?['pwh'] as num?)?.toDouble(),
      pwl: (period?['pwl'] as num?)?.toDouble(),
      pmh: (period?['pmh'] as num?)?.toDouble(),
      pml: (period?['pml'] as num?)?.toDouble(),
    );
  }
}

// ─── Per-underlying strategy group ───────────────────────────────────────────

class UnderlyingGroup {
  final String underlying;
  final List<LegRow> legs;
  final double dayPnl;
  final String? bucket; // null when not yet evaluated
  final double? score;
  final bool doneForDay;

  const UnderlyingGroup({
    required this.underlying,
    required this.legs,
    required this.dayPnl,
    this.bucket,
    this.score,
    required this.doneForDay,
  });

  factory UnderlyingGroup.fromJson(Map<String, dynamic> json) {
    final legsRaw = json['legs'] as List<dynamic>? ?? [];
    final totals = json['totals'] as Map<String, dynamic>? ?? {};
    final status = json['status'] as Map<String, dynamic>? ?? {};
    return UnderlyingGroup(
      underlying: json['underlying'] as String? ?? '',
      legs: legsRaw.map((l) => LegRow.fromJson(l as Map<String, dynamic>)).toList(),
      dayPnl: (totals['day_pnl'] as num?)?.toDouble() ?? 0.0,
      bucket: status['bucket'] as String?,
      score: (status['score'] as num?)?.toDouble(),
      doneForDay: status['done_for_day'] as bool? ?? false,
    );
  }
}

// ─── Monitor snapshot ─────────────────────────────────────────────────────────

class MonitorSnapshot {
  final List<IndexPrice> indices;
  final List<UnderlyingGroup> groups;
  final double dayRealized;
  final double dayUnrealized;
  final double dayPnl;
  final String? bucket; // NIFTY primary bucket; null before 10:15
  final double? score;
  final bool doneForDay;
  final int nOpenShorts;
  final int nOpenHedges;
  final int nOpenMomentum;
  final List<Map<String, dynamic>> recentEvents;
  final Map<String, SidIndicators> indicators;

  const MonitorSnapshot({
    required this.indices,
    required this.groups,
    required this.dayRealized,
    required this.dayUnrealized,
    required this.dayPnl,
    this.bucket,
    this.score,
    required this.doneForDay,
    required this.nOpenShorts,
    required this.nOpenHedges,
    required this.nOpenMomentum,
    required this.recentEvents,
    required this.indicators,
  });

  List<LegRow> get legs => groups.expand((g) => g.legs).toList();

  factory MonitorSnapshot.fromJson(Map<String, dynamic> json) {
    // Indices
    final indicesRaw = json['indices'] as Map<String, dynamic>? ?? {};
    final indices = indicesRaw.entries
        .map((e) => IndexPrice.fromJson(e.key, e.value as Map<String, dynamic>))
        .toList();

    // Groups (per-underlying with legs + per-underlying status)
    final groupsRaw = json['groups'] as List<dynamic>? ?? [];
    final groups = groupsRaw
        .map((g) => UnderlyingGroup.fromJson(g as Map<String, dynamic>))
        .toList();

    // Totals
    final totals = json['totals'] as Map<String, dynamic>? ?? {};

    // Status (primary = NIFTY)
    final status = json['status'] as Map<String, dynamic>? ?? {};

    // Indicators
    final indicatorsRaw = json['indicators'] as Map<String, dynamic>? ?? {};
    final indicators = indicatorsRaw.map(
      (sid, v) => MapEntry(sid, SidIndicators.fromJson(sid, v as Map<String, dynamic>)),
    );

    // Events
    final eventsRaw = json['recent_events'] as List<dynamic>? ?? [];
    final recentEvents =
        eventsRaw.map((e) => Map<String, dynamic>.from(e as Map)).toList();

    return MonitorSnapshot(
      indices: indices,
      groups: groups,
      dayRealized: (totals['day_realized'] as num?)?.toDouble() ?? 0.0,
      dayUnrealized: (totals['day_unrealized'] as num?)?.toDouble() ?? 0.0,
      dayPnl: (totals['day_pnl'] as num?)?.toDouble() ?? 0.0,
      bucket: status['bucket'] as String?,
      score: (status['score'] as num?)?.toDouble(),
      doneForDay: status['done_for_day'] as bool? ?? false,
      nOpenShorts: (status['n_open_shorts'] as num?)?.toInt() ?? 0,
      nOpenHedges: (status['n_open_hedges'] as num?)?.toInt() ?? 0,
      nOpenMomentum: (status['n_open_momentum'] as num?)?.toInt() ?? 0,
      recentEvents: recentEvents,
      indicators: indicators,
    );
  }
}

// ─── Strangle P&L ──────────────────────────────────────────────────────────────

class StranglePnlRow {
  final String underlying;
  final String strategyId;
  final double dayRealized;
  final double dayUnrealized;
  final double dayPnl;
  final int nOpenLegs;
  final bool doneForDay;
  final String? squaredOffAt;

  const StranglePnlRow({
    required this.underlying,
    required this.strategyId,
    required this.dayRealized,
    required this.dayUnrealized,
    required this.dayPnl,
    required this.nOpenLegs,
    required this.doneForDay,
    this.squaredOffAt,
  });

  factory StranglePnlRow.fromJson(Map<String, dynamic> json) {
    return StranglePnlRow(
      underlying: json['underlying'] as String? ?? '',
      strategyId: json['strategy_id'] as String? ?? '',
      dayRealized: (json['day_realized'] as num?)?.toDouble() ?? 0.0,
      dayUnrealized: (json['day_unrealized'] as num?)?.toDouble() ?? 0.0,
      dayPnl: (json['day_pnl'] as num?)?.toDouble() ?? 0.0,
      nOpenLegs: (json['n_open_legs'] as num?)?.toInt() ?? 0,
      doneForDay: json['done_for_day'] as bool? ?? false,
      squaredOffAt: json['squared_off_at'] as String?,
    );
  }
}

class StranglePnl {
  final List<StranglePnlRow> byIndex;
  final double totalRealized;
  final double totalUnrealized;
  final double totalPnl;
  final int totalOpenLegs;

  const StranglePnl({
    required this.byIndex,
    required this.totalRealized,
    required this.totalUnrealized,
    required this.totalPnl,
    required this.totalOpenLegs,
  });

  factory StranglePnl.fromJson(Map<String, dynamic> json) {
    final byIndexRaw = json['by_index'] as List<dynamic>? ?? [];
    final totals = json['totals'] as Map<String, dynamic>? ?? {};
    return StranglePnl(
      byIndex: byIndexRaw.map((e) => StranglePnlRow.fromJson(e as Map<String, dynamic>)).toList(),
      totalRealized: (totals['day_realized'] as num?)?.toDouble() ?? 0.0,
      totalUnrealized: (totals['day_unrealized'] as num?)?.toDouble() ?? 0.0,
      totalPnl: (totals['day_pnl'] as num?)?.toDouble() ?? 0.0,
      totalOpenLegs: (totals['n_open_legs'] as num?)?.toInt() ?? 0,
    );
  }
}

// ─── Strangle Trades ──────────────────────────────────────────────────────────

class StrangleTradeRow {
  final String? underlying;
  final String? symbol;
  final String? optType;
  final double? strike;
  final String? expiry;
  final double lots;
  final double? entryPrice;
  final String? entryTime;
  final double? exitPrice;
  final String? exitTime;
  final double? pnl;
  final bool open;
  final bool isHedge;

  const StrangleTradeRow({
    this.underlying,
    this.symbol,
    this.optType,
    this.strike,
    this.expiry,
    required this.lots,
    this.entryPrice,
    this.entryTime,
    this.exitPrice,
    this.exitTime,
    this.pnl,
    required this.open,
    required this.isHedge,
  });

  factory StrangleTradeRow.fromJson(Map<String, dynamic> json) {
    return StrangleTradeRow(
      underlying: json['underlying'] as String?,
      symbol: json['symbol'] as String?,
      optType: json['opt_type'] as String?,
      strike: (json['strike'] as num?)?.toDouble(),
      expiry: json['expiry'] as String?,
      lots: (json['lots'] as num?)?.toDouble() ?? 0.0,
      entryPrice: (json['entry_price'] as num?)?.toDouble(),
      entryTime: json['entry_time'] as String?,
      exitPrice: (json['exit_price'] as num?)?.toDouble(),
      exitTime: json['exit_time'] as String?,
      pnl: (json['pnl'] as num?)?.toDouble(),
      open: json['open'] as bool? ?? false,
      isHedge: json['is_hedge'] as bool? ?? false,
    );
  }
}

class StrangleTrades {
  final String date;
  final Map<String, List<StrangleTradeRow>> byIndex;

  const StrangleTrades({
    required this.date,
    required this.byIndex,
  });

  factory StrangleTrades.fromJson(Map<String, dynamic> json) {
    final Map<String, List<StrangleTradeRow>> parsedByIndex = {};
    if (json['by_index'] != null) {
      final map = json['by_index'] as Map<String, dynamic>;
      for (final entry in map.entries) {
        final list = entry.value as List?;
        if (list != null) {
          parsedByIndex[entry.key] = list
              .map((e) => StrangleTradeRow.fromJson(e as Map<String, dynamic>))
              .toList();
        }
      }
    }
    return StrangleTrades(
      date: json['date'] as String? ?? '',
      byIndex: parsedByIndex,
    );
  }
}
