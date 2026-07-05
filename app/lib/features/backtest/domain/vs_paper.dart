/// One day's backtest-vs-paper alignment.
class DayDivergence {
  const DayDivergence({
    required this.date,
    required this.backtestNet,
    required this.paperNet,
    required this.divergence,
    required this.diverges,
    this.cause,
  });

  final String date;
  final double? backtestNet;
  final double? paperNet;
  final double? divergence;
  final bool diverges;
  final String? cause;

  factory DayDivergence.fromJson(Map<String, dynamic> json) {
    return DayDivergence(
      date: json['date'] as String,
      backtestNet: (json['backtest_net'] as num?)?.toDouble(),
      paperNet: (json['paper_net'] as num?)?.toDouble(),
      divergence: (json['divergence'] as num?)?.toDouble(),
      diverges: json['diverges'] as bool? ?? false,
      cause: json['cause'] as String?,
    );
  }
}

/// The `GET /runs/{id}/vs-paper?granularity=day` response.
class VsPaperDayResult {
  const VsPaperDayResult({
    required this.runId,
    required this.strategyId,
    required this.paperDataAvailable,
    required this.days,
  });

  final String runId;
  final String strategyId;
  final bool paperDataAvailable;
  final List<DayDivergence> days;

  factory VsPaperDayResult.fromJson(Map<String, dynamic> json) {
    return VsPaperDayResult(
      runId: json['run_id'] as String,
      strategyId: json['strategy_id'] as String? ?? '',
      paperDataAvailable: json['paper_data_available'] as bool? ?? false,
      days: (json['days'] as List<dynamic>? ?? [])
          .map((e) => DayDivergence.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
    );
  }
}

/// One backtest or live decision event inside a minute bucket.
class MinuteSideEvent {
  const MinuteSideEvent({
    required this.side,
    required this.tsIst,
    required this.minute,
    required this.action,
    this.subReason,
    this.snapshot = const {},
  });

  final String side;
  final String tsIst;
  final String minute;
  final String action;
  final String? subReason;
  final Map<String, dynamic> snapshot;

  factory MinuteSideEvent.fromJson(Map<String, dynamic> json) {
    return MinuteSideEvent(
      side: json['side'] as String? ?? '',
      tsIst: json['ts_ist'] as String? ?? '',
      minute: json['minute'] as String? ?? '',
      action: json['action'] as String? ?? '',
      subReason: json['sub_reason'] as String?,
      snapshot: json['snapshot'] as Map<String, dynamic>? ?? const {},
    );
  }
}

/// One minute's backtest-vs-live event bucket, with mismatch flag.
class MinuteBucket {
  const MinuteBucket({
    required this.minute,
    required this.backtest,
    required this.live,
    required this.mismatch,
    this.cause,
  });

  final String minute;
  final List<MinuteSideEvent> backtest;
  final List<MinuteSideEvent> live;
  final bool mismatch;
  final String? cause;

  factory MinuteBucket.fromJson(Map<String, dynamic> json) {
    return MinuteBucket(
      minute: json['minute'] as String,
      backtest: (json['backtest'] as List<dynamic>? ?? [])
          .map((e) => MinuteSideEvent.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
      live: (json['live'] as List<dynamic>? ?? [])
          .map((e) => MinuteSideEvent.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
      mismatch: json['mismatch'] as bool? ?? false,
      cause: json['cause'] as String?,
    );
  }
}

/// The `GET /runs/{id}/vs-paper?granularity=minute&date=...` response.
class VsPaperMinuteResult {
  const VsPaperMinuteResult({
    required this.runId,
    required this.strategyId,
    required this.date,
    required this.minutes,
  });

  final String runId;
  final String strategyId;
  final String date;
  final List<MinuteBucket> minutes;

  factory VsPaperMinuteResult.fromJson(Map<String, dynamic> json) {
    return VsPaperMinuteResult(
      runId: json['run_id'] as String,
      strategyId: json['strategy_id'] as String? ?? '',
      date: json['date'] as String,
      minutes: (json['minutes'] as List<dynamic>? ?? [])
          .map((e) => MinuteBucket.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
    );
  }
}
