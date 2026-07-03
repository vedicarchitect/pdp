import '../domain/events_models.dart';

abstract class EventsSource {
  /// Stream of events + config state
  Stream<EventsData> watch();

  /// Patch the config for a specific event type
  Future<void> patchConfig({required String eventType, required bool pushEnabled});
}
