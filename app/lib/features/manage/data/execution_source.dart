/// Abstract source interface for the strategy execution monitor.
///
/// Concrete impls: [LiveExecutionSource] (real API), mock for tests.
library;

import '../domain/execution_models.dart';

abstract class ExecutionSource {
  Future<MonitorSnapshot> fetchMonitor({int nEvents = 20});
}
