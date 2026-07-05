import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/network/api_client.dart';
import '../data/backtest_live_source.dart';
import '../data/backtest_mock_source.dart';
import '../data/backtest_source.dart';
import '../domain/coverage.dart';
import '../domain/folds.dart';
import '../domain/job.dart';
import '../domain/models.dart';
import '../domain/promotion.dart';
import '../domain/strategy_info.dart';
import '../domain/sweep.dart';
import '../domain/vs_paper.dart';

/// Selects the live or mock source based on [AppConfig.useMock]. The same
/// [BacktestSource] interface is returned either way.
final backtestSourceProvider = Provider<BacktestSource>((ref) {
  const config = AppConfig.current;
  if (config.useMock) {
    return BacktestMockSource();
  }
  return BacktestLiveSource(api: ApiClient(), wsBase: config.wsBase);
});

/// Filters + sort applied to the runs table.
class RunsFilter {
  const RunsFilter({
    this.kind,
    this.strategyId,
    this.verdict,
    this.underlying,
    this.sortBy = 'created_at',
    this.sortDir = -1,
  });

  final String? kind;
  final String? strategyId;
  final String? verdict;
  final String? underlying;
  final String sortBy;
  final int sortDir;

  RunsFilter copyWith({
    String? Function()? kind,
    String? Function()? strategyId,
    String? Function()? verdict,
    String? Function()? underlying,
    String? sortBy,
    int? sortDir,
  }) {
    return RunsFilter(
      kind: kind != null ? kind() : this.kind,
      strategyId: strategyId != null ? strategyId() : this.strategyId,
      verdict: verdict != null ? verdict() : this.verdict,
      underlying: underlying != null ? underlying() : this.underlying,
      sortBy: sortBy ?? this.sortBy,
      sortDir: sortDir ?? this.sortDir,
    );
  }
}

final runsFilterProvider = NotifierProvider<RunsFilterNotifier, RunsFilter>(RunsFilterNotifier.new);

class RunsFilterNotifier extends Notifier<RunsFilter> {
  @override
  RunsFilter build() => const RunsFilter();

  void update(RunsFilter Function(RunsFilter) fn) => state = fn(state);
}

final backtestRunsProvider = FutureProvider.autoDispose<RunsPage>((ref) {
  final source = ref.watch(backtestSourceProvider);
  final filter = ref.watch(runsFilterProvider);
  return source.getRuns(
    kind: filter.kind,
    strategyId: filter.underlying == null ? filter.strategyId : null,
    verdict: filter.verdict,
    sortBy: filter.sortBy,
    sortDir: filter.sortDir,
    limit: 200,
  );
});

final backtestRunDetailProvider =
    FutureProvider.family.autoDispose<BacktestRun, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getRun(runId);
});

final backtestEquityProvider =
    FutureProvider.family.autoDispose<List<EquityPoint>, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getEquity(runId);
});

final backtestDaysProvider =
    FutureProvider.family.autoDispose<List<BacktestDay>, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getDays(runId);
});

typedef TradesKey = ({String runId, String date});

final backtestTradesProvider =
    FutureProvider.family.autoDispose<List<TradeFill>, TradesKey>((ref, key) {
  return ref.watch(backtestSourceProvider).getTrades(key.runId, key.date);
});

typedef DecisionsKey = ({String runId, String? date, bool full});

final backtestDecisionsProvider =
    FutureProvider.family.autoDispose<List<DecisionEvent>, DecisionsKey>((ref, key) {
  return ref.watch(backtestSourceProvider).getDecisions(key.runId, date: key.date, full: key.full);
});

final backtestFoldsProvider =
    FutureProvider.family.autoDispose<FoldsResult, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getFolds(runId);
});

final backtestSweepProvider =
    FutureProvider.family.autoDispose<SweepDoc, String>((ref, sweepId) {
  return ref.watch(backtestSourceProvider).getSweep(sweepId);
});

final promotionEvidenceProvider =
    FutureProvider.family.autoDispose<PromotionEvidence, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getPromotionEvidence(runId);
});

final vsPaperDayProvider =
    FutureProvider.family.autoDispose<VsPaperDayResult, String>((ref, runId) {
  return ref.watch(backtestSourceProvider).getVsPaperDay(runId);
});

typedef VsPaperMinuteKey = ({String runId, String date});

final vsPaperMinuteProvider =
    FutureProvider.family.autoDispose<VsPaperMinuteResult, VsPaperMinuteKey>((ref, key) {
  return ref.watch(backtestSourceProvider).getVsPaperMinute(key.runId, key.date);
});

/// Underlying selected for the coverage panel; `null` shows all three.
final coverageUnderlyingProvider = StateProvider<String?>((ref) => null);

final coverageProvider = FutureProvider.autoDispose<CoverageResponse>((ref) {
  final underlying = ref.watch(coverageUnderlyingProvider);
  return ref.watch(backtestSourceProvider).getCoverage(underlying: underlying);
});

final strategiesProvider = FutureProvider.autoDispose<List<StrategyInfo>>((ref) {
  return ref.watch(backtestSourceProvider).getStrategies();
});

/// Live progress for a launched job; completes the stream on a terminal frame.
final jobProgressProvider =
    StreamProvider.family.autoDispose<JobProgress, String>((ref, jobId) {
  return ref.watch(backtestSourceProvider).watchJob(jobId);
});

/// Sweep ids seen this session (there is no "list sweeps" endpoint — a sweep
/// id is captured from its launch job result), most recent first.
final recentSweepIdsProvider = NotifierProvider<RecentSweepIds, List<String>>(RecentSweepIds.new);

class RecentSweepIds extends Notifier<List<String>> {
  @override
  List<String> build() => const [];

  void add(String sweepId) {
    if (state.contains(sweepId)) return;
    state = [sweepId, ...state];
  }
}
