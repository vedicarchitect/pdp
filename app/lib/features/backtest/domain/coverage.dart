/// Coverage stats for one data family (spot/options/vix/levels/futures) within
/// an underlying's window.
class FamilyCoverage {
  const FamilyCoverage({
    required this.minDate,
    required this.maxDate,
    required this.coveredDays,
    required this.totalDays,
    required this.coveragePct,
    required this.gapRanges,
    this.status,
    this.note,
  });

  final String? minDate;
  final String? maxDate;
  final int coveredDays;
  final int totalDays;
  final double coveragePct;
  final List<List<String>> gapRanges;
  final String? status;
  final String? note;

  bool get isUnavailable => status == 'unavailable';

  factory FamilyCoverage.fromJson(Map<String, dynamic> json) {
    return FamilyCoverage(
      minDate: json['min_date'] as String?,
      maxDate: json['max_date'] as String?,
      coveredDays: (json['covered_days'] as num?)?.toInt() ?? 0,
      totalDays: (json['total_days'] as num?)?.toInt() ?? 0,
      coveragePct: (json['coverage_pct'] as num?)?.toDouble() ?? 0,
      gapRanges: (json['gap_ranges'] as List<dynamic>? ?? [])
          .map((e) => (e as List<dynamic>).map((s) => s as String).toList())
          .toList(growable: false),
      status: json['status'] as String?,
      note: json['note'] as String?,
    );
  }
}

/// One underlying's (NIFTY/BANKNIFTY/SENSEX) coverage across all families,
/// plus a per-date gap radar.
class UnderlyingCoverage {
  const UnderlyingCoverage({
    required this.underlying,
    required this.families,
    required this.radar,
  });

  final String underlying;
  final Map<String, FamilyCoverage> families;

  /// date -> family -> status string (e.g. "ready" or "VIX missing").
  final Map<String, Map<String, String>> radar;

  factory UnderlyingCoverage.fromJson(Map<String, dynamic> json) {
    final rawFamilies = json['families'] as Map<String, dynamic>? ?? const {};
    final rawRadar = json['radar'] as Map<String, dynamic>? ?? const {};
    return UnderlyingCoverage(
      underlying: json['underlying'] as String,
      families: rawFamilies.map(
        (k, v) => MapEntry(k, FamilyCoverage.fromJson(v as Map<String, dynamic>)),
      ),
      radar: rawRadar.map(
        (date, statuses) => MapEntry(
          date,
          (statuses as Map<String, dynamic>).map((k, v) => MapEntry(k, v as String)),
        ),
      ),
    );
  }

  /// Dates where at least one family is not "ready".
  List<String> get gappedDates =>
      radar.entries.where((e) => e.value.values.any((s) => s != 'ready')).map((e) => e.key).toList()..sort();
}

/// The full `GET /api/v1/coverage` response.
class CoverageResponse {
  const CoverageResponse({required this.from, required this.to, required this.underlyings});

  final String from;
  final String to;
  final Map<String, UnderlyingCoverage> underlyings;

  factory CoverageResponse.fromJson(Map<String, dynamic> json) {
    final window = json['window'] as Map<String, dynamic>? ?? const {};
    final rawUnderlyings = json['underlyings'] as Map<String, dynamic>? ?? const {};
    return CoverageResponse(
      from: window['from'] as String? ?? '',
      to: window['to'] as String? ?? '',
      underlyings: rawUnderlyings.map(
        (k, v) => MapEntry(k, UnderlyingCoverage.fromJson(v as Map<String, dynamic>)),
      ),
    );
  }
}
