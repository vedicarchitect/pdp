import '../domain/dashboard_models.dart';

/// Abstract source for dashboard data (live vs mock).
abstract class DashboardSource {
  Stream<DashboardData> streamDashboard();
}
