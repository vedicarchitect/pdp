import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/screener_repository.dart';
import '../domain/screener_models.dart';

final screenerRepositoryProvider = Provider<ScreenerRepository>((ref) {
  return ScreenerRepository(ApiClient());
});

final screenerStrategyProvider = StateProvider<String>((ref) {
  return 'ema_alignment';
});

final screenerResultsProvider = FutureProvider.autoDispose<List<ScreenerResult>>((ref) async {
  final strategy = ref.watch(screenerStrategyProvider);
  return ref.watch(screenerRepositoryProvider).runScreener(strategy);
});
