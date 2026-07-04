/// One PASS/REVIEW threshold check (e.g. profit-factor > 1.2).
class VerdictCheck {
  const VerdictCheck({required this.actual, required this.threshold, required this.pass});

  final double actual;
  final double threshold;
  final bool pass;

  factory VerdictCheck.fromJson(Map<String, dynamic> json) {
    return VerdictCheck(
      actual: (json['actual'] as num?)?.toDouble() ?? 0,
      threshold: (json['threshold'] as num?)?.toDouble() ?? 0,
      pass: json['pass'] as bool? ?? false,
    );
  }
}

/// The per-threshold breakdown backing a PASS/REVIEW verdict.
class VerdictBreakdown {
  const VerdictBreakdown({
    required this.checks,
    required this.allPass,
    required this.positiveFolds,
    required this.folds,
  });

  final Map<String, VerdictCheck> checks;
  final bool allPass;
  final int positiveFolds;
  final int folds;

  factory VerdictBreakdown.fromJson(Map<String, dynamic> json) {
    final rawChecks = json['checks'] as Map<String, dynamic>? ?? const {};
    return VerdictBreakdown(
      checks: rawChecks.map(
        (k, v) => MapEntry(k, VerdictCheck.fromJson(v as Map<String, dynamic>)),
      ),
      allPass: json['all_pass'] as bool? ?? false,
      positiveFolds: (json['positive_folds'] as num?)?.toInt() ?? 0,
      folds: (json['folds'] as num?)?.toInt() ?? 0,
    );
  }
}

/// The persisted evidence snapshot from `GET /runs/{id}/promotion`, recorded
/// at the time a PASS run was promoted to paper.
class PromotionEvidence {
  const PromotionEvidence({
    required this.runId,
    required this.sourceRunId,
    required this.strategyId,
    required this.yamlPath,
    required this.verdict,
    required this.stitchedOos,
    required this.promotedAt,
    this.verdictBreakdown,
    this.note,
  });

  final String runId;
  final String sourceRunId;
  final String strategyId;
  final String yamlPath;
  final String? verdict;
  final Map<String, dynamic> stitchedOos;
  final VerdictBreakdown? verdictBreakdown;
  final String? note;
  final DateTime promotedAt;

  factory PromotionEvidence.fromJson(Map<String, dynamic> json) {
    return PromotionEvidence(
      runId: json['run_id'] as String,
      sourceRunId: json['source_run_id'] as String,
      strategyId: json['strategy_id'] as String,
      yamlPath: json['yaml_path'] as String? ?? '',
      verdict: json['verdict'] as String?,
      stitchedOos: json['stitched_oos'] as Map<String, dynamic>? ?? const {},
      verdictBreakdown: json['verdict_breakdown'] is Map<String, dynamic>
          ? VerdictBreakdown.fromJson(json['verdict_breakdown'] as Map<String, dynamic>)
          : null,
      note: json['note'] as String?,
      promotedAt: DateTime.parse(json['promoted_at'] as String),
    );
  }
}
