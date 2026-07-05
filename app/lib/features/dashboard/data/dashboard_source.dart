import '../domain/dashboard_models.dart';

/// Abstract source for dashboard data (live vs mock), house convention.
abstract interface class DashboardSource {
  /// Seeds from a single REST call, then applies live deltas over the existing
  /// `/ws/market` + `/ws/portfolio` sockets — never opens a new socket.
  Stream<DashboardData> streamDashboard();
}
