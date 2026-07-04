/// Compile-time backend configuration.
///
/// Override at launch with `--dart-define`:
///   flutter run --dart-define=API_BASE=http://192.168.1.10:8000 \
///               --dart-define=WS_BASE=ws://192.168.1.10:8000 \
///               --dart-define=USE_MOCK=true
class AppConfig {
  const AppConfig({
    required this.apiBase,
    required this.wsBase,
    required this.useMock,
    required this.dashboardsBase,
  });

  /// REST base, e.g. `http://localhost:8000`. Paths are appended under `/api/v1`.
  final String apiBase;

  /// WebSocket base, e.g. `ws://localhost:8000`. Paths are appended under `/ws`.
  final String wsBase;

  /// When true, the app runs on a simulated live feed and never touches a backend.
  final bool useMock;

  /// OpenSearch Dashboards base, e.g. `http://localhost:5601`, for deep links
  /// into the backtest/coverage dashboards (`task search:up`).
  final String dashboardsBase;

  static const AppConfig current = AppConfig(
    apiBase: String.fromEnvironment('API_BASE', defaultValue: 'http://localhost:8000'),
    wsBase: String.fromEnvironment('WS_BASE', defaultValue: 'ws://localhost:8000'),
    useMock: bool.fromEnvironment('USE_MOCK'),
    dashboardsBase:
        String.fromEnvironment('DASHBOARDS_BASE', defaultValue: 'http://localhost:5601'),
  );
}
