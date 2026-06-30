class ScreenerResult {
  final String symbol;
  final double lastPrice;
  final double changePct;
  final int volume;
  final List<String> matchingCriteria;

  ScreenerResult({
    required this.symbol,
    required this.lastPrice,
    required this.changePct,
    required this.volume,
    required this.matchingCriteria,
  });

  factory ScreenerResult.fromJson(Map<String, dynamic> json) {
    return ScreenerResult(
      symbol: json['symbol'] as String? ?? '',
      lastPrice: (json['last_price'] as num?)?.toDouble() ?? 0.0,
      changePct: (json['change_pct'] as num?)?.toDouble() ?? 0.0,
      volume: (json['volume'] as num?)?.toInt() ?? 0,
      matchingCriteria: (json['matching_criteria'] as List?)?.map((e) => e as String).toList() ?? [],
    );
  }
}
