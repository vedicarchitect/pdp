import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../../portfolio/application/portfolio_providers.dart';
import '../data/dashboard_source.dart';
import '../data/live_dashboard_source.dart';
import '../data/mock_dashboard_source.dart';
import '../data/watchlist_repository.dart';
import '../domain/dashboard_models.dart';

final _dashboardWsClientProvider = Provider<WsClient>((ref) {
  const config = AppConfig.current;
  final ws = WsClient(url: '${config.wsBase}/ws/market');
  ref.onDispose(ws.dispose);
  return ws;
});

final dashboardSourceProvider = Provider<DashboardSource>((ref) {
  if (AppConfig.current.useMock) {
    return MockDashboardSource();
  }
  return LiveDashboardSource(
    api: ApiClient(),
    ws: ref.watch(_dashboardWsClientProvider),
    portfolioSource: ref.watch(portfolioSourceProvider),
  );
});

final dashboardStreamProvider = StreamProvider<DashboardData>((ref) {
  final source = ref.watch(dashboardSourceProvider);
  return source.streamDashboard();
});

final watchlistRepositoryProvider = Provider<WatchlistRepository>((ref) {
  if (AppConfig.current.useMock) {
    return InMemoryWatchlistRepository();
  }
  return SharedPrefsWatchlistRepository();
});

/// The user's saved watchlist symbols, persisted via [WatchlistRepository].
class WatchlistNotifier extends AsyncNotifier<List<String>> {
  @override
  Future<List<String>> build() => ref.read(watchlistRepositoryProvider).load();

  Future<void> add(String symbol) async {
    final trimmed = symbol.trim().toUpperCase();
    if (trimmed.isEmpty) return;
    final current = state.value ?? const [];
    if (current.contains(trimmed)) return;
    final next = [...current, trimmed];
    state = AsyncValue.data(next);
    await ref.read(watchlistRepositoryProvider).save(next);
  }

  Future<void> remove(String symbol) async {
    final current = state.value ?? const [];
    final next = current.where((s) => s != symbol).toList();
    state = AsyncValue.data(next);
    await ref.read(watchlistRepositoryProvider).save(next);
  }
}

final watchlistProvider = AsyncNotifierProvider<WatchlistNotifier, List<String>>(WatchlistNotifier.new);
