import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/risk_repository.dart';
import '../domain/risk_models.dart';

final riskRepositoryProvider = Provider<RiskRepository>((ref) {
  return RiskRepository(ApiClient());
});

final riskSettingsProvider = FutureProvider<RiskSettings>((ref) async {
  return ref.watch(riskRepositoryProvider).getRiskSettings();
});

final dailyLossStatusProvider = FutureProvider.autoDispose<DailyLossStatus>((ref) async {
  return ref.watch(riskRepositoryProvider).getDailyLoss();
});
