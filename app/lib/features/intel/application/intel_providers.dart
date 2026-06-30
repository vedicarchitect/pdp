import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/intel_repository.dart';
import '../domain/models.dart';

final intelRepositoryProvider = Provider<IntelRepository>((ref) {
  return IntelRepository(ApiClient());
});

final newsProvider = FutureProvider.autoDispose<List<NewsArticle>>((ref) {
  final repo = ref.watch(intelRepositoryProvider);
  return repo.getNews();
});

final sentimentProvider = FutureProvider.autoDispose<SentimentScore>((ref) {
  final repo = ref.watch(intelRepositoryProvider);
  return repo.getSentiment();
});

final commoditiesProvider = FutureProvider.autoDispose<List<CommodityPrice>>((ref) {
  final repo = ref.watch(intelRepositoryProvider);
  return repo.getCommodities();
});

final calendarProvider = FutureProvider.autoDispose<List<EconomicEvent>>((ref) {
  final repo = ref.watch(intelRepositoryProvider);
  return repo.getCalendar();
});
