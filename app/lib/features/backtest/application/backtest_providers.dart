import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/api_client.dart';
import '../data/backtest_repository.dart';
import '../domain/models.dart';

final backtestRepositoryProvider = Provider<BacktestRepository>((ref) {
  return BacktestRepository(ApiClient());
});

final backtestRunsProvider = FutureProvider.autoDispose<List<BacktestRun>>((ref) {
  final repo = ref.watch(backtestRepositoryProvider);
  return repo.getRuns();
});

final backtestRunDetailProvider = FutureProvider.family.autoDispose<BacktestRun, String>((ref, runId) {
  final repo = ref.watch(backtestRepositoryProvider);
  return repo.getRun(runId);
});

final backtestRunEquityProvider = FutureProvider.family.autoDispose<List<BacktestEquityDay>, String>((ref, runId) {
  final repo = ref.watch(backtestRepositoryProvider);
  return repo.getRunEquity(runId);
});
