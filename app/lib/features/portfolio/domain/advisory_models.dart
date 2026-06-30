class HoldingOverview {
  final String sector;
  final double percentage;
  final double value;

  const HoldingOverview({
    required this.sector,
    required this.percentage,
    required this.value,
  });

  factory HoldingOverview.fromJson(Map<String, dynamic> json) {
    return HoldingOverview(
      sector: json['sector'] as String,
      percentage: (json['percentage'] as num).toDouble(),
      value: (json['value'] as num).toDouble(),
    );
  }
}

class AllocationAdvice {
  final String id;
  final String title;
  final String description;
  final String action;
  final String severity; // high, medium, low

  const AllocationAdvice({
    required this.id,
    required this.title,
    required this.description,
    required this.action,
    required this.severity,
  });

  factory AllocationAdvice.fromJson(Map<String, dynamic> json) {
    return AllocationAdvice(
      id: json['id'] as String,
      title: json['title'] as String,
      description: json['description'] as String,
      action: json['action'] as String,
      severity: json['severity'] as String,
    );
  }
}

class HistoricalPnlData {
  final DateTime date;
  final double pnl;
  final double value;

  const HistoricalPnlData({
    required this.date,
    required this.pnl,
    required this.value,
  });

  factory HistoricalPnlData.fromJson(Map<String, dynamic> json) {
    return HistoricalPnlData(
      date: DateTime.parse(json['date'] as String),
      pnl: (json['pnl'] as num).toDouble(),
      value: (json['value'] as num).toDouble(),
    );
  }
}
