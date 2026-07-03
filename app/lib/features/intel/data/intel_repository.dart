import '../../../core/network/api_client.dart';
import '../domain/models.dart';

class IntelRepository {
  final ApiClient _api;

  IntelRepository(this._api);

  Future<List<NewsArticle>> getNews() async {
    final response = await _api.getJson('/api/v1/intel/news');
    final articles = response['articles'] as List;
    return articles.map((e) => NewsArticle.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<SentimentScore> getSentiment() async {
    final response = await _api.getJson('/api/v1/intel/sentiment');
    return SentimentScore.fromJson(response);
  }

  Future<List<CommodityPrice>> getCommodities() async {
    final response = await _api.getJson('/api/v1/intel/commodities');
    final commodities = response['commodities'] as List;
    return commodities.map((e) => CommodityPrice.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<EconomicEvent>> getCalendar() async {
    final response = await _api.getJson('/api/v1/intel/calendar');
    final events = response['events'] as List;
    return events.map((e) => EconomicEvent.fromJson(e as Map<String, dynamic>)).toList();
  }
}
