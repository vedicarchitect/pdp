/// Polls GET /api/v1/strangle/monitor every N seconds and emits MonitorSnapshot.
library;

import '../../../core/network/api_client.dart';
import '../domain/execution_models.dart';
import 'execution_source.dart';

class LiveExecutionSource implements ExecutionSource {
  final ApiClient _api;

  LiveExecutionSource(this._api);

  @override
  Future<MonitorSnapshot> fetchMonitor({int nEvents = 20}) async {
    final json = await _api.getJson(
      '/api/v1/strangle/monitor?n_events=$nEvents',
    );
    return MonitorSnapshot.fromJson(json);
  }
}
