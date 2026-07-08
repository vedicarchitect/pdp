import '../../../core/network/api_client.dart';
import '../domain/journal_models.dart';

class JournalRepository {
  final ApiClient _api;

  JournalRepository(this._api);

  Future<JournalDay> getJournalDay(String date) async {
    final response = await _api.getJson('/api/v1/journal?date=$date');
    return JournalDay.fromJson(response);
  }

  Future<void> updateMetadata(
    String date,
    String notes,
    List<String> tags,
    List<String> screenshots,
  ) async {
    await _api.putJson('/api/v1/journal/$date/metadata', body: {
      'notes': notes,
      'tags': tags,
      'screenshots': screenshots,
    });
  }

  Future<JournalStats> getStrategyStats(String strategyId, String date) async {
    final response = await _api.getJson('/api/v1/journal/strategy/$strategyId?date=$date');
    // Non-strangle strategies return {stats: {...}}; strangle strategies (routed
    // through the trade ledger) return {totals: {...}} instead — no 'stats' key.
    final statsJson = response['stats'] as Map<String, dynamic>? ??
        response['totals'] as Map<String, dynamic>? ??
        {};
    return JournalStats.fromJson(statsJson);
  }
}
