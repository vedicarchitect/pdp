import '../../../core/network/api_client.dart';
import '../domain/models.dart';

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
}
