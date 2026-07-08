import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/network/api_client.dart';
import '../data/execution_source.dart';
import '../data/live_execution_source.dart';
import '../data/manage_repository.dart';
import '../domain/execution_models.dart';
import '../domain/models.dart';

final manageRepositoryProvider = Provider<ManageRepository>((ref) {
  return ManageRepository(ApiClient());
});

final strategiesProvider = FutureProvider.autoDispose<List<StrategyInfo>>((ref) {
  final repo = ref.watch(manageRepositoryProvider);
  return repo.getStrategies();
});

// A StateProvider to hold the currently selected date for the Journal
final journalDateProvider = StateProvider<DateTime>((ref) => DateTime.now());

final journalEntriesProvider = FutureProvider.autoDispose<List<JournalEntry>>((ref) {
  final repo = ref.watch(manageRepositoryProvider);
  final date = ref.watch(journalDateProvider);
  final formattedDate = DateFormat('yyyy-MM-dd').format(date);
  return repo.getJournal(formattedDate);
});

final journalStatsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) {
  final repo = ref.watch(manageRepositoryProvider);
  final date = ref.watch(journalDateProvider);
  final formattedDate = DateFormat('yyyy-MM-dd').format(date);
  return repo.getJournalStats(formattedDate);
});

final jobsProvider = FutureProvider.autoDispose<List<JobRecord>>((ref) {
  final repo = ref.watch(manageRepositoryProvider);
  return repo.getJobs();
});

// ─── Execution monitor ────────────────────────────────────────────────────────

final liveExecutionSourceProvider = Provider<ExecutionSource>((ref) {
  return LiveExecutionSource(ApiClient());
});

/// Polls the monitor endpoint every 5 s while the tab is mounted.
final monitorStreamProvider = StreamProvider.autoDispose<MonitorSnapshot>((ref) {
  final source = ref.watch(liveExecutionSourceProvider);
  return Stream.periodic(
    const Duration(seconds: 2),
    (_) => source.fetchMonitor(),
  ).asyncMap((future) => future);
});

/// Manual one-shot refresh (pull-to-refresh / refresh button).
final monitorRefreshProvider = FutureProvider.autoDispose<MonitorSnapshot>((ref) {
  final source = ref.watch(liveExecutionSourceProvider);
  return source.fetchMonitor();
});

final stranglePnlProvider = FutureProvider.autoDispose<StranglePnl>((ref) {
  final repo = ref.watch(manageRepositoryProvider);
  return repo.getStranglePnl();
});

final strangleTradesProvider = FutureProvider.autoDispose.family<StrangleTrades, String>((ref, date) {
  final repo = ref.watch(manageRepositoryProvider);
  return repo.getStrangleTrades(date);
});
