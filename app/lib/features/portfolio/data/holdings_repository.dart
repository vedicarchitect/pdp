import '../../../core/network/api_client.dart';
import '../domain/holdings_models.dart';

class HoldingsRepository {
  final ApiClient _api;

  HoldingsRepository(this._api);

  Future<Map<String, dynamic>> getHoldings() async {
    final response = await _api.getJson('/api/v1/portfolio/holdings');
    final summary = HoldingsSummary.fromJson(response['summary'] as Map<String, dynamic>);
    final holdings = (response['holdings'] as List)
        .map((e) => HoldingDetail.fromJson(e as Map<String, dynamic>))
        .toList();
    return {
      'summary': summary,
      'holdings': holdings,
      'is_mock': response['is_mock'] as bool? ?? false,
    };
  }

  Future<List<PositionDetail>> getPositions() async {
    final response = await _api.getJson('/api/v1/broker-sync/positions');
    final positions = (response['positions'] as List?)
            ?.map((e) => PositionDetail.fromJson(e as Map<String, dynamic>))
            .toList() ??
        [];
    return positions;
  }
}
