import 'dart:async';

import '../domain/coverage.dart';
import '../domain/folds.dart';
import '../domain/job.dart';
import '../domain/models.dart';
import '../domain/promotion.dart';
import '../domain/strategy_info.dart';
import '../domain/sweep.dart';
import '../domain/vs_paper.dart';

/// A source of backtest-console data. Implemented by both the real backend
/// ([BacktestLiveSource]) and the offline simulation ([BacktestMockSource]),
/// so the presentation layer never branches on data origin.
abstract interface class BacktestSource {
  Future<RunsPage> getRuns({
    String? kind,
    String? strategyId,
    String? verdict,
    String sortBy,
    int sortDir,
    int limit,
    int offset,
  });

  Future<BacktestRun> getRun(String runId);

  Future<List<EquityPoint>> getEquity(String runId);

  Future<List<BacktestDay>> getDays(String runId);

  Future<List<TradeFill>> getTrades(String runId, String date);

  Future<List<DecisionEvent>> getDecisions(String runId, {String? date, bool full});

  Future<FoldsResult> getFolds(String runId);

  Future<SweepDoc> getSweep(String sweepId);

  Future<String> launchSingle(Map<String, dynamic> request);

  Future<String> launchSweep(Map<String, dynamic> request);

  Future<String> launchWalkforward(Map<String, dynamic> request);

  Future<void> promoteRun(String runId, {String? note});

  Future<PromotionEvidence> getPromotionEvidence(String runId);

  Future<VsPaperDayResult> getVsPaperDay(String runId);

  Future<VsPaperMinuteResult> getVsPaperMinute(String runId, String date);

  Future<CoverageResponse> getCoverage({String? from, String? to, String? underlying});

  Future<String> runHousekeeping(String taskName, Map<String, dynamic> params);

  Future<List<StrategyInfo>> getStrategies();

  Future<JobRecord> getJob(String jobId);

  /// Emits a [JobProgress] frame per WS message until a terminal message.
  Stream<JobProgress> watchJob(String jobId);
}
