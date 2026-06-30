class AppEvent {
  const AppEvent({
    required this.id,
    required this.securityId,
    required this.eventType,
    required this.severity,
    required this.message,
    required this.timestamp,
  });

  final String id;
  final String? securityId;
  final String eventType;
  final String severity; // 'info', 'warning', 'alert'
  final String message;
  final DateTime timestamp;

  factory AppEvent.fromJson(Map<String, dynamic> json) {
    return AppEvent(
      id: json['id'] as String,
      securityId: json['security_id'] as String?,
      eventType: json['event_type'] as String,
      severity: json['severity'] as String,
      message: json['message'] as String,
      timestamp: DateTime.parse(json['timestamp'] as String),
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
