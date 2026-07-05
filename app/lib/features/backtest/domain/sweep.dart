/// One ranked parameter combination in a sweep leaderboard.
class SweepCombo {
  const SweepCombo({required this.params, required this.metrics, required this.rank});

  final Map<String, dynamic> params;
  final Map<String, dynamic> metrics;
  final int rank;

  double? get profitFactor => (metrics['profit_factor'] as num?)?.toDouble();
  double? get net => (metrics['net'] as num?)?.toDouble();

  factory SweepCombo.fromJson(Map<String, dynamic> json) {
    return SweepCombo(
      params: json['params'] as Map<String, dynamic>? ?? const {},
      metrics: json['metrics'] as Map<String, dynamic>? ?? const {},
      rank: (json['rank'] as num?)?.toInt() ?? 0,
    );
  }
}

/// The full `GET /sweeps/{id}` leaderboard document.
class SweepDoc {
  const SweepDoc({
    required this.sweepId,
    required this.kind,
    required this.grid,
    required this.objective,
    required this.combos,
    required this.createdAt,
    this.bestParam,
  });

  final String sweepId;
  final String kind;
  final Map<String, dynamic> grid;
  final String objective;
  final List<SweepCombo> combos;
  final Map<String, dynamic>? bestParam;
  final DateTime createdAt;

  factory SweepDoc.fromJson(Map<String, dynamic> json) {
    return SweepDoc(
      sweepId: json['sweep_id'] as String,
      kind: json['kind'] as String? ?? 'sweep',
      grid: json['grid'] as Map<String, dynamic>? ?? const {},
      objective: json['objective'] as String? ?? 'pf',
      combos: (json['combos'] as List<dynamic>? ?? [])
          .map((e) => SweepCombo.fromJson(e as Map<String, dynamic>))
          .toList(growable: false),
      bestParam: json['best_param'] as Map<String, dynamic>?,
      createdAt: json['created_at'] != null
          ? DateTime.parse(json['created_at'] as String)
          : DateTime.now(),
    );
  }
}
