import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/holdings_repository.dart';

final holdingsRepositoryProvider = Provider<HoldingsRepository>((ref) {
  return HoldingsRepository(ApiClient());
});

final holdingsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) {
  return ref.watch(holdingsRepositoryProvider).getHoldings();
});
