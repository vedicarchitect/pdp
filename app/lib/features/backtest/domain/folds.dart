/// Aggregate out-of-sample metrics stitched across all walk-forward folds.
class StitchedOos {
  const StitchedOos({
    required this.net,
    required this.profitFactor,
    required this.sharpe,
    required this.trades,
    required this.days,
    required this.folds,
    required this.positiveFolds,
  });

  final double net;
  final double? profitFactor;
  final double? sharpe;
  final int trades;
  final int days;
  final int folds;
  final int positiveFolds;

  double get positiveFoldFraction => folds == 0 ? 0 : positiveFolds / folds;

  factory StitchedOos.fromJson(Map<String, dynamic> json) {
    return StitchedOos(
      net: (json['net'] as num?)?.toDouble() ?? 0,
      profitFactor: (json['profit_factor'] as num?)?.toDouble(),
      sharpe: (json['sharpe'] as num?)?.toDouble(),
      trades: (json['trades'] as num?)?.toInt() ?? 0,
      days: (json['days'] as num?)?.toInt() ?? 0,
      folds: (json['folds'] as num?)?.toInt() ?? 0,
      positiveFolds: (json['positive_folds'] as num?)?.toInt() ?? 0,
    );
  }
}

class FoldWindow {
  const FoldWindow({required this.start, required this.end});

  final String start;
  final String end;

  factory FoldWindow.fromJson(Map<String, dynamic> json) {
    return FoldWindow(start: json['start'] as String, end: json['end'] as String);
  }
}

/// One walk-forward fold's IS (in-sample) vs OOS (out-of-sample) metrics.
class Fold {
  const Fold({
    required this.foldIndex,
    required this.isWindow,
    required this.oosWindow,
    required this.pickLabel,
    required this.isMetrics,
    required this.oosMetrics,
  });

  final int foldIndex;
  final FoldWindow isWindow;
  final FoldWindow oosWindow;
  final String pickLabel;
  final Map<String, dynamic> isMetrics;
  final Map<String, dynamic> oosMetrics;

  double? get oosProfitFactor => (oosMetrics['profit_factor'] as num?)?.toDouble();
  double? get oosNet => (oosMetrics['net'] as num?)?.toDouble();
  bool get isPositive => (oosNet ?? 0) > 0;

  factory Fold.fromJson(Map<String, dynamic> json) {
    return Fold(
      foldIndex: (json['fold_index'] as num?)?.toInt() ?? 0,
      isWindow: FoldWindow.fromJson(json['is_window'] as Map<String, dynamic>),
      oosWindow: FoldWindow.fromJson(json['oos_window'] as Map<String, dynamic>),
      pickLabel: json['pick_label'] as String? ?? '',
      isMetrics: json['is_metrics'] as Map<String, dynamic>? ?? const {},
      oosMetrics: json['oos_metrics'] as Map<String, dynamic>? ?? const {},
    );
  }
}

/// The full `GET /runs/{id}/folds` response.
class FoldsResult {
  const FoldsResult({
    required this.runId,
    required this.verdict,
    required this.stitchedOos,
    required this.folds,
  });

  final String runId;
  final String? verdict;
  final StitchedOos? stitchedOos;
  final List<Fold> folds;

  factory FoldsResult.fromJson(Map<String, dynamic> json) {
    return FoldsResult(
      runId: json['run_id'] as String,
      verdict: json['verdict'] as String?,
      stitchedOos: json['stitched_oos'] is Map<String, dynamic>
          ? StitchedOos.fromJson(json['stitched_oos'] as Map<String, dynamic>)
          : null,
      folds: (json['folds'] as List<dynamic>? ?? [])
          .map((e) => Fold.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
    );
  }
}
