class AppEvent {
  const AppEvent({
    required this.id,
    required this.securityId,
    required this.underlying,
    required this.timeframe,
    required this.eventType,
    required this.severity,
    required this.title,
    required this.message,
    required this.timestamp,
  });

  final String id;
  final String? securityId;
  final String? underlying;
  final String? timeframe;
  final String eventType;
  final String severity; // normalised lowercase: 'info' | 'warning' | 'error' | 'critical'
  final String? title;
  final String message;
  final DateTime timestamp;

  factory AppEvent.fromJson(Map<String, dynamic> json) {
    // Backend Event.to_dict() emits `ts` (isoformat) and uppercase severity values
    // (INFO/WARNING/ERROR/CRITICAL). Read defensively and normalise here so the rest
    // of the app can switch on lowercase severities.
    final tsRaw = (json['ts'] ?? json['timestamp']) as String?;
    return AppEvent(
      id: (json['id'] ?? '').toString(),
      securityId: json['security_id'] as String?,
      underlying: json['underlying'] as String?,
      timeframe: json['timeframe'] as String?,
      eventType: (json['event_type'] ?? '').toString(),
      severity: (json['severity'] as String? ?? 'info').toLowerCase(),
      title: json['title'] as String?,
      message: (json['message'] ?? '').toString(),
      timestamp: tsRaw != null ? DateTime.parse(tsRaw) : DateTime.now(),
    );
  }
}

class EventConfig {
  const EventConfig({
    required this.pushEnabled,
    required this.eventTypePush,
  });

  final bool pushEnabled;
  final Map<String, bool> eventTypePush;

  factory EventConfig.fromJson(Map<String, dynamic> json) {
    return EventConfig(
      pushEnabled: json['push_enabled'] as bool? ?? false,
      eventTypePush: Map<String, bool>.from(json['event_type_push'] as Map? ?? {}),
    );
  }
}

class EventsData {
  const EventsData({
    required this.events,
    required this.config,
  });

  final List<AppEvent> events;
  final EventConfig config;
}
