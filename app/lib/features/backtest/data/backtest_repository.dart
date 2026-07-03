import '../../../core/network/api_client.dart';
import '../domain/models.dart';

class BacktestRepository {
  BacktestRepository(this._api);

  final ApiClient _api;

  Future<List<BacktestRun>> getRuns({
    String? kind,
    String? strategyId,
    String? verdict,
    String sortBy = 'created_at',
    int sortDir = -1,
    int limit = 50,
    int offset = 0,
  }) async {
    final query = <String, dynamic>{
      if (kind != null) 'kind': kind,
      if (strategyId != null) 'strategy_id': strategyId,
      if (verdict != null) 'verdict': verdict,
      'sort_by': sortBy,
      'sort_dir': sortDir,
      'limit': limit,
      'offset': offset,
    };
    
    final queryStr = query.entries.map((e) => '${e.key}=${e.value}').join('&');
    final response = await _api.getJson('/api/v1/strangle-backtests/runs?$queryStr');
    
    final runs = response['runs'] as List<dynamic>? ?? [];
    return runs.map((e) => BacktestRun.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<BacktestRun> getRun(String runId) async {
    final response = await _api.getJson('/api/v1/strangle-backtests/runs/$runId');
    return BacktestRun.fromJson(response);
  }

  Future<List<BacktestEquityDay>> getRunEquity(String runId) async {
    final response = await _api.getJson('/api/v1/strangle-backtests/runs/$runId/equity');
    final equity = response['equity'] as List<dynamic>? ?? [];
    return equity.map((e) => BacktestEquityDay.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<CompareResult>> compareRuns(List<String> runIds) async {
    final response = await _api.postJson('/api/v1/strangle-backtests/compare', body: {'run_ids': runIds});
    final runs = response['runs'] as List<dynamic>? ?? [];
    return runs.map((e) => CompareResult.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Map<String, dynamic>> launchSingle(Map<String, dynamic> request) async {
    return _api.postJson('/api/v1/strangle-backtests/runs', body: request);
  }

  Future<Map<String, dynamic>> launchSweep(Map<String, dynamic> request) async {
    return _api.postJson('/api/v1/strangle-backtests/sweeps', body: request);
  }

  Future<Map<String, dynamic>> launchWalkforward(Map<String, dynamic> request) async {
    return _api.postJson('/api/v1/strangle-backtests/walkforwards', body: request);
  }

  Future<Map<String, dynamic>> promoteRun(String runId) async {
    return _api.postJson('/api/v1/strangle-backtests/runs/$runId/promote');
  }
}
