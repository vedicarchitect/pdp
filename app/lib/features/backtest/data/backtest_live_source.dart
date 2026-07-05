import 'dart:async';

import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../domain/coverage.dart';
import '../domain/folds.dart';
import '../domain/job.dart';
import '../domain/models.dart';
import '../domain/promotion.dart';
import '../domain/strategy_info.dart';
import '../domain/sweep.dart';
import '../domain/vs_paper.dart';
import 'backtest_source.dart';

const String _base = '/api/v1/strangle-backtests';

/// Real backend source: REST calls under `/api/v1/strangle-backtests`,
/// `/api/v1/coverage`, `/api/v1/strategies`, `/api/v1/housekeeping`, and
/// `/api/v1/jobs`, plus `/ws/jobs/{id}` for live job progress.
class BacktestLiveSource implements BacktestSource {
  BacktestLiveSource({required this.api, required this.wsBase});

  final ApiClient api;
  final String wsBase;

  @override
  Future<RunsPage> getRuns({
    String? kind,
    String? strategyId,
    String? verdict,
    String sortBy = 'created_at',
    int sortDir = -1,
    int limit = 50,
    int offset = 0,
  }) async {
    final query = <String, String>{
      if (kind != null) 'kind': kind,
      if (strategyId != null) 'strategy_id': strategyId,
      if (verdict != null) 'verdict': verdict,
      'sort_by': sortBy,
      'sort_dir': '$sortDir',
      'limit': '$limit',
      'offset': '$offset',
    };
    final qs = query.entries.map((e) => '${e.key}=${Uri.encodeQueryComponent(e.value)}').join('&');
    final json = await api.getJson('$_base/runs?$qs');
    return RunsPage.fromJson(json);
  }

  @override
  Future<BacktestRun> getRun(String runId) async {
    final json = await api.getJson('$_base/runs/$runId');
    return BacktestRun.fromJson(json);
  }

  @override
  Future<List<EquityPoint>> getEquity(String runId) async {
    final json = await api.getJson('$_base/runs/$runId/equity');
    return (json['equity'] as List<dynamic>? ?? [])
        .map((e) => EquityPoint.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<List<BacktestDay>> getDays(String runId) async {
    final json = await api.getJson('$_base/runs/$runId/days');
    return (json['days'] as List<dynamic>? ?? [])
        .map((e) => BacktestDay.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<List<TradeFill>> getTrades(String runId, String date) async {
    final json = await api.getJson('$_base/runs/$runId/days/$date/trades');
    return (json['fills'] as List<dynamic>? ?? [])
        .map((e) => TradeFill.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<List<DecisionEvent>> getDecisions(String runId, {String? date, bool full = false}) async {
    final query = <String, String>{
      if (date != null) 'date': date,
      if (full) 'full': 'true',
    };
    final qs = query.entries.map((e) => '${e.key}=${e.value}').join('&');
    final path = qs.isEmpty ? '$_base/runs/$runId/decisions' : '$_base/runs/$runId/decisions?$qs';
    final json = await api.getJson(path);
    return (json['decisions'] as List<dynamic>? ?? [])
        .map((e) => DecisionEvent.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<FoldsResult> getFolds(String runId) async {
    final json = await api.getJson('$_base/runs/$runId/folds');
    return FoldsResult.fromJson(json);
  }

  @override
  Future<SweepDoc> getSweep(String sweepId) async {
    final json = await api.getJson('$_base/sweeps/$sweepId');
    return SweepDoc.fromJson(json);
  }

  @override
  Future<String> launchSingle(Map<String, dynamic> request) async {
    final json = await api.postJson('$_base/runs', body: request);
    return json['job_id'] as String;
  }

  @override
  Future<String> launchSweep(Map<String, dynamic> request) async {
    final json = await api.postJson('$_base/sweeps', body: request);
    return json['job_id'] as String;
  }

  @override
  Future<String> launchWalkforward(Map<String, dynamic> request) async {
    final json = await api.postJson('$_base/walkforwards', body: request);
    return json['job_id'] as String;
  }

  @override
  Future<void> promoteRun(String runId, {String? note}) async {
    await api.postJson('$_base/runs/$runId/promote', body: {if (note != null) 'note': note});
  }

  @override
  Future<PromotionEvidence> getPromotionEvidence(String runId) async {
    final json = await api.getJson('$_base/runs/$runId/promotion');
    return PromotionEvidence.fromJson(json);
  }

  @override
  Future<VsPaperDayResult> getVsPaperDay(String runId) async {
    final json = await api.getJson('$_base/runs/$runId/vs-paper?granularity=day');
    return VsPaperDayResult.fromJson(json);
  }

  @override
  Future<VsPaperMinuteResult> getVsPaperMinute(String runId, String date) async {
    final json = await api.getJson('$_base/runs/$runId/vs-paper?granularity=minute&date=$date');
    return VsPaperMinuteResult.fromJson(json);
  }

  @override
  Future<CoverageResponse> getCoverage({String? from, String? to, String? underlying}) async {
    final query = <String, String>{
      if (from != null) 'from': from,
      if (to != null) 'to': to,
      if (underlying != null) 'underlying': underlying,
    };
    final qs = query.entries.map((e) => '${e.key}=${e.value}').join('&');
    final path = qs.isEmpty ? '/api/v1/coverage' : '/api/v1/coverage?$qs';
    final json = await api.getJson(path);
    return CoverageResponse.fromJson(json);
  }

  @override
  Future<String> runHousekeeping(String taskName, Map<String, dynamic> params) async {
    final json = await api.postJson('/api/v1/housekeeping/$taskName', body: params);
    return json['job_id'] as String;
  }

  @override
  Future<List<StrategyInfo>> getStrategies() async {
    final json = await api.getJson('/api/v1/strategies');
    return (json['strategies'] as List<dynamic>? ?? [])
        .map((e) => StrategyInfo.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  @override
  Future<JobRecord> getJob(String jobId) async {
    final json = await api.getJson('/api/v1/jobs/$jobId');
    return JobRecord.fromJson(json);
  }

  @override
  Stream<JobProgress> watchJob(String jobId) async* {
    final ws = WsClient(url: '$wsBase/ws/jobs/$jobId');
    ws.connect();
    try {
      await for (final msg in ws.stream) {
        final progress = JobProgress.fromJson(msg);
        yield progress;
        if (progress.isTerminal) break;
      }
    } finally {
      await ws.dispose();
    }
  }
}
