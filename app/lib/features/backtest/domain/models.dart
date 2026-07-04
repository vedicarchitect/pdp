/// A backtest run summary as listed in the console and shown on run detail.
class BacktestRun {
  const BacktestRun({
    required this.runId,
    required this.kind,
    required this.strategyId,
    required this.canonicalStrategyId,
    required this.verdict,
    required this.createdAt,
    required this.metrics,
    required this.config,
    required this.status,
    required this.promotionState,
    this.gitSha,
    this.stitchedOos,
    this.window,
  });

  final String runId;
  final String kind;
  final String? strategyId;
  final String? canonicalStrategyId;
  final String? verdict;
  final DateTime createdAt;
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> config;
  final String status;
  final String promotionState;
  final String? gitSha;
  final Map<String, dynamic>? stitchedOos;
  final DateWindow? window;

  bool get isPromoted => promotionState == 'promoted';
  bool get isWalkforward => kind == 'walkforward';

  double? get profitFactor => (metrics['profit_factor'] as num?)?.toDouble();
  double? get sharpe => (metrics['sharpe'] as num?)?.toDouble();
  double? get maxDd => (metrics['max_dd'] as num?)?.toDouble();
  double? get net => (metrics['net'] as num?)?.toDouble();
  double? get winRate => (metrics['win_rate'] as num?)?.toDouble();
  double? get calmar => (metrics['calmar'] as num?)?.toDouble();
  int? get trades => (metrics['trades'] as num?)?.toInt();

  factory BacktestRun.fromJson(Map<String, dynamic> json) {
    return BacktestRun(
      runId: json['run_id'] as String,
      kind: json['kind'] as String? ?? 'single',
      strategyId: json['strategy_id'] as String?,
      canonicalStrategyId: json['canonical_strategy_id'] as String?,
      verdict: json['verdict'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      metrics: json['metrics'] as Map<String, dynamic>? ?? const {},
      config: json['config'] as Map<String, dynamic>? ?? const {},
      status: json['status'] as String? ?? 'complete',
      promotionState: json['promotion_state'] as String? ?? 'none',
      gitSha: json['git_sha'] as String?,
      stitchedOos: json['stitched_oos'] as Map<String, dynamic>?,
      window: json['window'] is Map<String, dynamic>
          ? DateWindow.fromJson(json['window'] as Map<String, dynamic>)
          : null,
    );
  }
}

/// A `{from, to}` date window.
class DateWindow {
  const DateWindow({required this.from, required this.to});

  final String from;
  final String to;

  factory DateWindow.fromJson(Map<String, dynamic> json) {
    return DateWindow(
      from: (json['from'] ?? json['start']) as String,
      to: (json['to'] ?? json['end']) as String,
    );
  }
}

/// A page of runs from `GET /runs`.
class RunsPage {
  const RunsPage({required this.total, required this.runs});

  final int total;
  final List<BacktestRun> runs;

  factory RunsPage.fromJson(Map<String, dynamic> json) {
    final runs = (json['runs'] as List<dynamic>? ?? [])
        .map((e) => BacktestRun.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
    return RunsPage(total: json['total'] as int? ?? runs.length, runs: runs);
  }
}

/// One day's equity + drawdown point.
class EquityPoint {
  const EquityPoint({
    required this.date,
    required this.net,
    required this.cumEquity,
    required this.peak,
    required this.drawdown,
  });

  final String date;
  final double net;
  final double cumEquity;
  final double peak;
  final double drawdown;

  factory EquityPoint.fromJson(Map<String, dynamic> json) {
    return EquityPoint(
      date: json['date'] as String,
      net: (json['net'] as num?)?.toDouble() ?? 0,
      cumEquity: (json['cum_equity'] as num?)?.toDouble() ?? 0,
      peak: (json['peak'] as num?)?.toDouble() ?? 0,
      drawdown: (json['drawdown'] as num?)?.toDouble() ?? 0,
    );
  }
}

/// A full per-day row from `GET /runs/{id}/days`.
class BacktestDay {
  const BacktestDay({
    required this.date,
    required this.expiry,
    required this.niftyOpen,
    required this.niftyClose,
    required this.niftyChg,
    required this.trades,
    required this.grossPnl,
    required this.commission,
    required this.net,
    required this.cumEquity,
    required this.peak,
    required this.drawdown,
    required this.halted,
    required this.buildMs,
    required this.simMs,
  });

  final String date;
  final String expiry;
  final double niftyOpen;
  final double niftyClose;
  final double niftyChg;
  final int trades;
  final double grossPnl;
  final double commission;
  final double net;
  final double cumEquity;
  final double peak;
  final double drawdown;
  final String halted;
  final double buildMs;
  final double simMs;

  factory BacktestDay.fromJson(Map<String, dynamic> json) {
    return BacktestDay(
      date: json['date'] as String,
      expiry: json['expiry'] as String? ?? '',
      niftyOpen: (json['nifty_open'] as num?)?.toDouble() ?? 0,
      niftyClose: (json['nifty_close'] as num?)?.toDouble() ?? 0,
      niftyChg: (json['nifty_chg'] as num?)?.toDouble() ?? 0,
      trades: (json['trades'] as num?)?.toInt() ?? 0,
      grossPnl: (json['gross_pnl'] as num?)?.toDouble() ?? 0,
      commission: (json['commission'] as num?)?.toDouble() ?? 0,
      net: (json['net'] as num?)?.toDouble() ?? 0,
      cumEquity: (json['cum_equity'] as num?)?.toDouble() ?? 0,
      peak: (json['peak'] as num?)?.toDouble() ?? 0,
      drawdown: (json['drawdown'] as num?)?.toDouble() ?? 0,
      halted: json['halted'] as String? ?? '',
      buildMs: (json['build_ms'] as num?)?.toDouble() ?? 0,
      simMs: (json['sim_ms'] as num?)?.toDouble() ?? 0,
    );
  }
}

/// A single fill from `GET /runs/{id}/days/{date}/trades`.
class TradeFill {
  const TradeFill({
    required this.time,
    required this.side,
    required this.optType,
    required this.strike,
    required this.qty,
    required this.price,
    required this.nifty,
    required this.dayPnl,
    required this.commission,
    required this.note,
    this.legPnl,
  });

  final String time;
  final String side;
  final String optType;
  final double strike;
  final int qty;
  final double price;
  final double nifty;
  final double? legPnl;
  final double dayPnl;
  final double commission;
  final String note;

  factory TradeFill.fromJson(Map<String, dynamic> json) {
    return TradeFill(
      time: json['time'] as String? ?? '',
      side: json['side'] as String? ?? '',
      optType: json['opt_type'] as String? ?? '',
      strike: (json['strike'] as num?)?.toDouble() ?? 0,
      qty: (json['qty'] as num?)?.toInt() ?? 0,
      price: (json['price'] as num?)?.toDouble() ?? 0,
      nifty: (json['nifty'] as num?)?.toDouble() ?? 0,
      legPnl: (json['leg_pnl'] as num?)?.toDouble(),
      dayPnl: (json['day_pnl'] as num?)?.toDouble() ?? 0,
      commission: (json['commission'] as num?)?.toDouble() ?? 0,
      note: json['note'] as String? ?? '',
    );
  }
}

/// One reason-coded decision event from the decision trace.
class DecisionEvent {
  const DecisionEvent({
    required this.tsIst,
    required this.date,
    required this.event,
    required this.action,
    this.subReason,
    this.snapshot = const {},
  });

  final String tsIst;
  final String date;
  final String event;
  final String? subReason;
  final String action;
  final Map<String, dynamic> snapshot;

  factory DecisionEvent.fromJson(Map<String, dynamic> json) {
    return DecisionEvent(
      tsIst: json['ts_ist'] as String? ?? '',
      date: json['date'] as String? ?? '',
      event: json['event'] as String? ?? '',
      subReason: json['sub_reason'] as String?,
      action: json['action'] as String? ?? '',
      snapshot: json['snapshot'] as Map<String, dynamic>? ?? const {},
    );
  }
}
