import '../../../core/network/api_client.dart';
import '../domain/advisory_models.dart';

class AdvisoryRepository {
  final ApiClient _api;

  AdvisoryRepository(this._api);

  Future<Map<String, dynamic>> getAdvisory() async {
    final response = await _api.getJson('/api/v1/portfolio/advisory');
    final holdings = (response['holdings'] as List)
        .map((e) => HoldingOverview.fromJson(e as Map<String, dynamic>))
        .toList();
    final advice = (response['advice'] as List)
        .map((e) => AllocationAdvice.fromJson(e as Map<String, dynamic>))
        .toList();
    return {
      'holdings': holdings,
      'advice': advice,
      'is_mock': response['is_mock'] as bool? ?? false,
    };
  }

  Future<List<HistoricalPnlData>> getHistory() async {
    final response = await _api.getJson('/api/v1/portfolio/history');
    final history = response['history'] as List;
    return history
        .map((e) => HistoricalPnlData.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
