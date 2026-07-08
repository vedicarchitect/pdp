import 'dart:async';
import 'dart:math';

import '../domain/events_models.dart';
import 'events_source.dart';

class MockEventsSource implements EventsSource {
  MockEventsSource() {
    _emit();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _generateEvent());
  }

  late final Timer _timer;
  final _controller = StreamController<EventsData>.broadcast();

  final List<AppEvent> _events = [];
  EventConfig _config = const EventConfig(
    pushEnabled: true,
    eventTypePush: {
      'crossover': true,
      'breakout': true,
      'anomaly': false,
    },
  );

  final _rand = Random();

  void _emit() {
    _controller.add(EventsData(events: List.unmodifiable(_events), config: _config));
  }

  void _generateEvent() {
    final severities = ['info', 'warning', 'critical'];
    final types = ['EMA_CROSS', 'SUPERTREND_FLIP', 'CAMARILLA_TOUCH', 'LEVEL_BREAK'];
    final indices = ['NIFTY', 'BANKNIFTY', 'SENSEX'];
    final tfs = ['5m', '15m', '30m', '1H', '1D'];

    final idx = indices[_rand.nextInt(indices.length)];
    final event = AppEvent(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      securityId: idx,
      underlying: idx,
      timeframe: tfs[_rand.nextInt(tfs.length)],
      eventType: types[_rand.nextInt(types.length)],
      severity: severities[_rand.nextInt(severities.length)],
      title: 'Simulated event',
      message: 'Simulated event: Price crossed threshold.',
      timestamp: DateTime.now(),
    );

    _events.insert(0, event);
    if (_events.length > 50) _events.removeLast();
    _emit();
  }

  @override
  Stream<EventsData> watch() => _controller.stream;

  @override
  Future<void> patchConfig({required String eventType, required bool pushEnabled}) async {
    final newMap = Map<String, bool>.from(_config.eventTypePush);
    newMap[eventType] = pushEnabled;
    _config = EventConfig(pushEnabled: _config.pushEnabled, eventTypePush: newMap);
    _emit();
  }

  void dispose() {
    _timer.cancel();
    _controller.close();
  }
}
