import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../data/events_source.dart';
import '../data/live_events_source.dart';
import '../data/mock_events_source.dart';
import '../domain/events_models.dart';

final _eventsWsClientProvider = Provider<WsClient>((ref) {
  const config = AppConfig.current;
  final ws = WsClient(url: '${config.wsBase}/ws/events');
  ref.onDispose(ws.dispose);
  return ws;
});

final eventsSourceProvider = Provider<EventsSource>((ref) {
  if (AppConfig.current.useMock) {
    final mock = MockEventsSource();
    ref.onDispose(mock.dispose);
    return mock;
  }
  final live = LiveEventsSource(
    api: ApiClient(),
    ws: ref.watch(_eventsWsClientProvider),
  );
  ref.onDispose(live.dispose);
  return live;
});

final eventsStreamProvider = StreamProvider<EventsData>((ref) {
  final source = ref.watch(eventsSourceProvider);
  return source.watch();
});
