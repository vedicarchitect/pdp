import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/network/api_client.dart';
import '../data/manage_repository.dart';
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
