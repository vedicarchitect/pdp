import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/journal_repository.dart';
import '../domain/journal_models.dart';

final journalRepositoryProvider = Provider<JournalRepository>((ref) {
  return JournalRepository(ApiClient());
});

final journalDateProvider = StateProvider<DateTime>((ref) {
  return DateTime.now();
});

final journalDayProvider = FutureProvider.autoDispose<JournalDay>((ref) {
  final date = ref.watch(journalDateProvider);
  final formattedDate = '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
  return ref.watch(journalRepositoryProvider).getJournalDay(formattedDate);
});
