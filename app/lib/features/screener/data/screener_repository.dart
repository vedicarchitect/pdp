import '../../../core/network/api_client.dart';
import '../domain/screener_models.dart';

class ScreenerRepository {
  final ApiClient _api;

  ScreenerRepository(this._api);

  Future<List<ScreenerResult>> runScreener(String strategy) async {
    final response = await _api.getJson('/api/v1/screener/run?strategy=$strategy');
    final results = response['results'] as List?;
    if (results == null) return [];
    return results.map((e) => ScreenerResult.fromJson(e as Map<String, dynamic>)).toList();
  }
}
