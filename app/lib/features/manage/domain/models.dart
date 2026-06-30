class StrategyInfo {
  final String id;
  final String status;
  final String? instrument;
  final String? interval;

  StrategyInfo({
    required this.id,
    required this.status,
    this.instrument,
    this.interval,
  });

  factory StrategyInfo.fromJson(Map<String, dynamic> json) {
    return StrategyInfo(
      id: json['id'] as String,
      status: json['status'] as String,
      instrument: json['instrument'] as String?,
      interval: json['interval'] as String?,
    );
  }
}

class JournalEntry {
  final String date;
  final String type;
  final Map<String, dynamic> data;

  JournalEntry({
    required this.date,
    required this.type,
    required this.data,
  });

  factory JournalEntry.fromJson(Map<String, dynamic> json) {
    return JournalEntry(
      date: json['date'] as String,
      type: json['type'] ?? 'unknown',
      data: json,
    );
  }
}

class JobRecord {
  final String id;
  final String type;
  final String status;
  final DateTime createdAt;

  JobRecord({
    required this.id,
    required this.type,
    required this.status,
    required this.createdAt,
  });

  factory JobRecord.fromJson(Map<String, dynamic> json) {
    return JobRecord(
      id: json['id'] as String,
      type: json['type'] as String,
      status: json['status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
    );
  }
}
