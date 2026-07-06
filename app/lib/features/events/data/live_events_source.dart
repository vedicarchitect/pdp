import 'dart:async';

import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../domain/events_models.dart';
import 'events_source.dart';

class LiveEventsSource implements EventsSource {
  LiveEventsSource({
    required this.api,
    required this.ws,
  }) {
    _init();
  }

  final ApiClient api;
  final WsClient ws;

  final _controller = StreamController<EventsData>.broadcast();
  List<AppEvent> _events = [];
  EventConfig _config = const EventConfig(pushEnabled: false, eventTypePush: {});

  StreamSubscription? _wsSub;

  Future<void> _init() async {
    try {
      final configJson = await api.getJson('/api/v1/events/config');
      _config = EventConfig.fromJson(configJson);

      final eventsJson = await api.getJson('/api/v1/events?limit=50');
      final list = (eventsJson['events'] as List?) ?? [];
      _events = list.map((e) => AppEvent.fromJson(e as Map<String, dynamic>)).toList();
      _emit();

      ws.connect();
      _wsSub = ws.stream.listen((msg) {
        // Backend EventsHub.publish sends Event.to_dict() directly — there is no
        // `type` envelope. Accept any frame carrying an `event_type` (and skip the
        // hub's control frames, e.g. heartbeats).
        if (msg['event_type'] != null) {
          final evt = AppEvent.fromJson(msg);
          _events.insert(0, evt);
          if (_events.length > 100) _events.removeLast();
          _emit();
        }
      });
    } catch (_) {
      // Best effort
      _emit();
    }
  }

  void _emit() {
    if (!_controller.isClosed) {
      _controller.add(EventsData(events: List.unmodifiable(_events), config: _config));
    }
  }

  @override
  Stream<EventsData> watch() => _controller.stream;

  @override
  Future<void> patchConfig({required String eventType, required bool pushEnabled}) async {
    try {
      await api.patchJson('/api/v1/events/config', body: {
        'event_type': eventType,
        'push_enabled': pushEnabled,
      });
      final newMap = Map<String, bool>.from(_config.eventTypePush);
      newMap[eventType] = pushEnabled;
      _config = EventConfig(pushEnabled: _config.pushEnabled, eventTypePush: newMap);
      _emit();
    } catch (_) {
      // Revert or show error ideally
    }
  }

  void dispose() {
    _wsSub?.cancel();
    _controller.close();
  }
}
