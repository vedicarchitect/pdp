import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/network/api_client.dart';
import '../../../core/network/connection_status.dart';
import '../../../core/network/ws_client.dart';
import '../data/live_portfolio_source.dart';
import '../data/mock_portfolio_source.dart';
import '../data/portfolio_source.dart';
import '../domain/portfolio_snapshot.dart';

/// Selects the live or mock source based on [AppConfig.useMock]. The same
/// [PortfolioSource] interface is returned either way.
final portfolioSourceProvider = Provider<PortfolioSource>((ref) {
  const config = AppConfig.current;
  if (config.useMock) {
    return MockPortfolioSource();
  }
  final ws = WsClient(
    url: '${config.wsBase}/ws/portfolio',
    onStatus: (status) =>
        ref.read(connectionStatusProvider.notifier).state = status,
  );
  ref.onDispose(ws.dispose);
  return LivePortfolioSource(api: ApiClient(), ws: ws);
});

/// The live portfolio snapshot stream the UI watches.
final portfolioProvider = StreamProvider<PortfolioSnapshot>((ref) {
  if (AppConfig.current.useMock) {
    // No socket in mock mode — report a healthy connection for the badge.
    Future.microtask(() =>
        ref.read(connectionStatusProvider.notifier).state = ConnStatus.connected);
  }
  return ref.watch(portfolioSourceProvider).watch();
});

/// Trade mode (`paper` / `live`) derived from the latest snapshot; defaults to
/// `paper` until data arrives.
final modeProvider = Provider<String>((ref) {
  return ref.watch(portfolioProvider).maybeWhen(
        data: (snap) => snap.summary.mode,
        orElse: () => 'paper',
      );
});

/// A rolling window of recent day-P&L values feeding the sparkline chart.
final pnlHistoryProvider =
    NotifierProvider<PnlHistory, List<double>>(PnlHistory.new);

class PnlHistory extends Notifier<List<double>> {
  static const int _maxPoints = 60;

  @override
  List<double> build() {
    ref.listen(portfolioProvider, (_, next) {
      next.whenData((snap) {
        final updated = [...state, snap.summary.dayPnl];
        state = updated.length > _maxPoints
            ? updated.sublist(updated.length - _maxPoints)
            : updated;
      });
    });
    return const [];
  }
}
