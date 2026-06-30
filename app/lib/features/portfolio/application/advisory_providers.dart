import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/advisory_repository.dart';
import '../domain/advisory_models.dart';

final advisoryRepositoryProvider = Provider<AdvisoryRepository>((ref) {
  return AdvisoryRepository(ApiClient());
});

final advisoryProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) {
  return ref.watch(advisoryRepositoryProvider).getAdvisory();
});

final historyProvider = FutureProvider.autoDispose<List<HistoricalPnlData>>((ref) {
  return ref.watch(advisoryRepositoryProvider).getHistory();
});
