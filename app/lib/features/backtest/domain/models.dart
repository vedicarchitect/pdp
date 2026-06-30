class BacktestRun {
  const BacktestRun({
    required this.runId,
    required this.kind,
    required this.strategyId,
    required this.verdict,
    required this.createdAt,
    required this.metrics,
    required this.config,
    this.stitchedOos,
    this.window,
  });

  final String runId;
  final String kind;
  final String? strategyId;
  final String? verdict;
  final DateTime createdAt;
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> config;
  final Map<String, dynamic>? stitchedOos;
  final Map<String, dynamic>? window;

  factory BacktestRun.fromJson(Map<String, dynamic> json) {
    return BacktestRun(
      runId: json['run_id'] as String,
      kind: json['kind'] as String? ?? 'single',
      strategyId: json['strategy_id'] as String?,
      verdict: json['verdict'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      metrics: json['metrics'] as Map<String, dynamic>? ?? {},
      config: json['config'] as Map<String, dynamic>? ?? {},
      stitchedOos: json['stitched_oos'] as Map<String, dynamic>?,
      window: json['window'] as Map<String, dynamic>?,
    );
  }
}

class BacktestEquityDay {
  const BacktestEquityDay({
    required this.date,
    required this.cumEquity,
    required this.drawdown,
    this.net,
    this.peak,
  });

  final String date;
  final double cumEquity;
  final double drawdown;
  final double? net;
  final double? peak;

  factory BacktestEquityDay.fromJson(Map<String, dynamic> json) {
    return BacktestEquityDay(
      date: json['date'] as String,
      cumEquity: (json['cum_equity'] as num).toDouble(),
      drawdown: (json['drawdown'] as num).toDouble(),
      net: (json['net'] as num?)?.toDouble(),
      peak: (json['peak'] as num?)?.toDouble(),
    );
  }
}

class CompareResult {
  const CompareResult({
    required this.runId,
    required this.metrics,
    this.kind,
    this.verdict,
    this.window,
    required this.equity,
  });

  final String runId;
  final Map<String, dynamic> metrics;
  final String? kind;
  final String? verdict;
  final Map<String, dynamic>? window;
  final List<BacktestEquityDay> equity;

  factory CompareResult.fromJson(Map<String, dynamic> json) {
    return CompareResult(
      runId: json['run_id'] as String,
      metrics: json['metrics'] as Map<String, dynamic>? ?? {},
      kind: json['kind'] as String?,
      verdict: json['verdict'] as String?,
      window: json['window'] as Map<String, dynamic>?,
      equity: (json['equity'] as List<dynamic>?)
              ?.map((e) => BacktestEquityDay.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
    );
  }
}
