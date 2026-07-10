import '../../../core/network/api_client.dart';
import '../domain/models.dart';
import '../domain/execution_models.dart';
import '../domain/broker_models.dart';

class ManageRepository {
  final ApiClient _api;

  ManageRepository(this._api);

  Future<List<StrategyInfo>> getStrategies() async {
    final res = await _api.getJson('/api/v1/strategies');
    final list = res['strategies'] as List<dynamic>;
    return list.map((e) => StrategyInfo.fromJson(e)).toList();
  }

  Future<void> startStrategy(String id) async {
    await _api.postJson('/api/v1/strategies/$id/start');
  }

  Future<void> stopStrategy(String id) async {
    await _api.postJson('/api/v1/strategies/$id/stop');
  }

  Future<List<JournalEntry>> getJournal(String date) async {
    final res = await _api.getJson('/api/v1/journal?date=$date');
    if (res['entries'] != null) {
      final list = res['entries'] as List<dynamic>;
      return list.map((e) => JournalEntry.fromJson(e)).toList();
    }
    return [];
  }

  Future<Map<String, dynamic>> getJournalStats(String date) async {
    return _api.getJson('/api/v1/journal/stats?date=$date');
  }

  Future<List<JobRecord>> getJobs() async {
    final res = await _api.getJson('/api/v1/jobs');
    final list = res['jobs'] as List<dynamic>;
    return list.map((e) => JobRecord.fromJson(e)).toList();
  }

  Future<void> cancelJob(String id) async {
    await _api.postJson('/api/v1/jobs/$id/cancel');
  }

  Future<void> deleteJob(String id) async {
    await _api.deleteJson('/api/v1/jobs/$id');
  }

  Future<void> runHousekeeping(String taskName, Map<String, dynamic> params) async {
    await _api.postJson('/api/v1/housekeeping/$taskName', body: params);
  }

  Future<StrangleTrades> getStrangleTrades(String date) async {
    final res = await _api.getJson('/api/v1/strangle/trades?date=$date');
    return StrangleTrades.fromJson(res);
  }

  Future<StranglePnl> getStranglePnl() async {
    final res = await _api.getJson('/api/v1/strangle/pnl');
    return StranglePnl.fromJson(res);
  }

  Future<BrokerSyncStatus> getBrokerSyncStatus() async {
    return BrokerSyncStatus.fromJson(await _api.getJson('/api/v1/broker-sync/status'));
  }

  /// Broker (Dhan) account view. `/status` is read first: the three report
  /// endpoints return 503 when sync is disabled, and an empty page is otherwise
  /// ambiguous between "never synced" and "flat account".
  Future<BrokerAccount> getBrokerAccount() async {
    final status = await getBrokerSyncStatus();
    if (status.state != BrokerSyncState.ready) {
      return BrokerAccount(state: status.state);
    }

    final results = await Future.wait([
      _api.getJson('/api/v1/broker-sync/holdings'),
      _api.getJson('/api/v1/broker-sync/positions'),
      _api.getJson('/api/v1/broker-sync/funds'),
    ]);
    List<Map<String, dynamic>> items(Map<String, dynamic> res) =>
        ((res['items'] as List?) ?? const [])
            .map((e) => e as Map<String, dynamic>)
            .toList();

    final holdings = items(results[0]).map(BrokerHolding.fromJson).toList();
    final positions = items(results[1]).map(BrokerPosition.fromJson).toList();
    final funds = items(results[2]);
    return BrokerAccount(
      state: BrokerSyncState.ready,
      holdings: holdings,
      positions: positions,
      fund: funds.isNotEmpty ? BrokerFund.fromJson(funds.first) : null,
    );
  }
}
