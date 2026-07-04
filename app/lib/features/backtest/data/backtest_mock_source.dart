import 'dart:async';
import 'dart:math';

import '../domain/coverage.dart';
import '../domain/folds.dart';
import '../domain/job.dart';
import '../domain/models.dart';
import '../domain/promotion.dart';
import '../domain/strategy_info.dart';
import '../domain/sweep.dart';
import '../domain/vs_paper.dart';
import 'backtest_source.dart';

/// Simulates the backtest console backend with zero network calls: a handful
/// of seeded runs (single + walk-forward), deterministic drill-down data, and
/// fake async jobs that report progress then land a new run. Used for widget
/// tests and `AppConfig.useMock` demos.
class BacktestMockSource implements BacktestSource {
  BacktestMockSource() : _runs = List.of(_seedRuns);

  final List<BacktestRun> _runs;
  final Map<String, JobRecord> _jobs = {};
  final Random _rng = Random(7);

  static final List<BacktestRun> _seedRuns = [
    BacktestRun(
      runId: 'strangle_20260701-093000',
      kind: 'single',
      strategyId: 'strangle',
      canonicalStrategyId: 'directional_strangle_nifty',
      verdict: 'PASS',
      createdAt: DateTime(2026, 7, 1, 9, 30),
      metrics: const {
        'net': 856000.0, 'profit_factor': 5.72, 'win_rate': 0.63,
        'max_dd': 71000.0, 'sharpe': 1.8, 'calmar': 12.1, 'trades': 412, 'halted': 3, 'days': 620,
      },
      config: const {'st': [10, 2], 'tf': 15, 'hedge_enabled': true},
      status: 'complete',
      promotionState: 'promoted',
      window: const DateWindow(from: '2021-01-01', to: '2026-06-26'),
    ),
    BacktestRun(
      runId: 'strangle_20260702-101500',
      kind: 'walkforward',
      strategyId: 'strangle',
      canonicalStrategyId: 'directional_strangle_banknifty',
      verdict: 'PASS',
      createdAt: DateTime(2026, 7, 2, 10, 15),
      metrics: const {
        'net': 3510000.0, 'profit_factor': 4.89, 'win_rate': 0.58,
        'max_dd': 210000.0, 'sharpe': 1.4, 'calmar': 8.3, 'trades': 890, 'halted': 6, 'days': 780,
      },
      config: const {'st': [10, 2], 'tf': 15, 'underlying': 'BANKNIFTY'},
      status: 'complete',
      promotionState: 'none',
      stitchedOos: const {'net': 3510000.0, 'profit_factor': 4.89, 'sharpe': 1.4, 'trades': 890, 'days': 780, 'folds': 5, 'positive_folds': 4},
      window: const DateWindow(from: '2023-01-01', to: '2026-06-29'),
    ),
    BacktestRun(
      runId: 'strangle_20260628-140000',
      kind: 'single',
      strategyId: 'strangle',
      canonicalStrategyId: 'directional_strangle_sensex',
      verdict: 'REVIEW',
      createdAt: DateTime(2026, 6, 28, 14, 0),
      metrics: const {
        'net': -42000.0, 'profit_factor': 0.91, 'win_rate': 0.41,
        'max_dd': 95000.0, 'sharpe': -0.2, 'calmar': -1.1, 'trades': 205, 'halted': 12, 'days': 300,
      },
      config: const {'st': [10, 2], 'tf': 15, 'underlying': 'SENSEX'},
      status: 'complete',
      promotionState: 'none',
      window: const DateWindow(from: '2024-01-01', to: '2026-03-30'),
    ),
  ];

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
    var filtered = _runs.where((r) {
      if (kind != null && r.kind != kind) return false;
      if (strategyId != null && r.canonicalStrategyId != strategyId && r.strategyId != strategyId) return false;
      if (verdict != null && r.verdict != verdict) return false;
      return true;
    }).toList();

    int cmp(BacktestRun a, BacktestRun b) {
      num av;
      num bv;
      switch (sortBy) {
        case 'pf':
        case 'profit_factor':
          av = a.profitFactor ?? 0;
          bv = b.profitFactor ?? 0;
        case 'net':
          av = a.net ?? 0;
          bv = b.net ?? 0;
        case 'max_dd':
          av = a.maxDd ?? 0;
          bv = b.maxDd ?? 0;
        case 'sharpe':
          av = a.sharpe ?? 0;
          bv = b.sharpe ?? 0;
        default:
          return sortDir < 0 ? b.createdAt.compareTo(a.createdAt) : a.createdAt.compareTo(b.createdAt);
      }
      return sortDir < 0 ? bv.compareTo(av) : av.compareTo(bv);
    }

    filtered.sort(cmp);
    final page = filtered.skip(offset).take(limit).toList(growable: false);
    return RunsPage(total: filtered.length, runs: page);
  }

  @override
  Future<BacktestRun> getRun(String runId) async {
    return _runs.firstWhere((r) => r.runId == runId, orElse: () => throw StateError('run not found: $runId'));
  }

  @override
  Future<List<EquityPoint>> getEquity(String runId) async {
    final run = await getRun(runId);
    final from = DateTime.tryParse(run.window?.from ?? '') ?? DateTime(2026, 1, 1);
    var cum = 0.0;
    var peak = 0.0;
    return List.generate(60, (i) {
      final date = from.add(Duration(days: i));
      final net = (_rng.nextDouble() - 0.42) * 25000;
      cum += net;
      peak = max(peak, cum);
      return EquityPoint(
        date: date.toIso8601String().substring(0, 10),
        net: net,
        cumEquity: cum,
        peak: peak,
        drawdown: cum - peak,
      );
    });
  }

  @override
  Future<List<BacktestDay>> getDays(String runId) async {
    final equity = await getEquity(runId);
    return equity.map((e) {
      final niftyOpen = 24000 + _rng.nextDouble() * 400;
      return BacktestDay(
        date: e.date,
        expiry: e.date,
        niftyOpen: niftyOpen,
        niftyClose: niftyOpen + (_rng.nextDouble() - 0.5) * 150,
        niftyChg: (_rng.nextDouble() - 0.5) * 150,
        trades: 1 + _rng.nextInt(4),
        grossPnl: e.net + 120,
        commission: 120,
        net: e.net,
        cumEquity: e.cumEquity,
        peak: e.peak,
        drawdown: e.drawdown,
        halted: e.net < -15000 ? 'day_loss_limit' : '',
        buildMs: 40 + _rng.nextDouble() * 20,
        simMs: 8 + _rng.nextDouble() * 6,
      );
    }).toList(growable: false);
  }

  @override
  Future<List<TradeFill>> getTrades(String runId, String date) async {
    return const [
      TradeFill(
        time: '09:20', side: 'SELL', optType: 'CE', strike: 24500, qty: 75, price: 142.5,
        nifty: 24480, legPnl: 3200, dayPnl: 3200, commission: 40, note: 'entry',
      ),
      TradeFill(
        time: '09:20', side: 'SELL', optType: 'PE', strike: 24300, qty: 75, price: 138.0,
        nifty: 24480, legPnl: -1200, dayPnl: 2000, commission: 40, note: 'entry',
      ),
      TradeFill(
        time: '15:20', side: 'BUY', optType: 'CE', strike: 24500, qty: 75, price: 98.0,
        nifty: 24410, legPnl: 3337.5, dayPnl: 5337.5, commission: 40, note: 'square_off',
      ),
    ];
  }

  @override
  Future<List<DecisionEvent>> getDecisions(String runId, {String? date, bool full = false}) async {
    final d = date ?? (await getEquity(runId)).first.date;
    return [
      DecisionEvent(tsIst: '$d 09:15:00', date: d, event: 'st_flip', action: 'bias_up', snapshot: const {'st_dir': 1}),
      DecisionEvent(tsIst: '$d 09:20:00', date: d, event: 'entry', action: 'sell_strangle', snapshot: const {'ce_strike': 24500, 'pe_strike': 24300}),
      DecisionEvent(tsIst: '$d 12:05:00', date: d, event: 'scale_in', subReason: 'momentum_confirm', action: 'add_leg', snapshot: const {}),
      DecisionEvent(tsIst: '$d 15:20:00', date: d, event: 'exit', subReason: 'day_end', action: 'square_off', snapshot: const {}),
    ];
  }

  @override
  Future<FoldsResult> getFolds(String runId) async {
    final run = await getRun(runId);
    if (!run.isWalkforward) {
      return FoldsResult(runId: runId, verdict: run.verdict, stitchedOos: null, folds: const []);
    }
    final folds = List.generate(5, (i) {
      return Fold(
        foldIndex: i,
        isWindow: FoldWindow(start: '2023-0${i + 1}-01', end: '2023-1$i-30'),
        oosWindow: FoldWindow(start: '2023-1$i-01', end: '2024-0${i + 1}-28'),
        pickLabel: 'st(10,2)/15m',
        isMetrics: {'net': 200000.0 + i * 5000, 'profit_factor': 3.2 + i * 0.1, 'sharpe': 1.1},
        oosMetrics: {
          'net': i == 2 ? -12000.0 : 60000.0 + i * 8000,
          'profit_factor': i == 2 ? 0.85 : 2.4 + i * 0.2,
          'win_rate': 0.55,
          'sharpe': i == 2 ? -0.1 : 1.2,
          'max_dd': 30000.0,
          'days': 60,
          'trades': 90,
        },
      );
    });
    return FoldsResult(
      runId: runId,
      verdict: run.verdict,
      stitchedOos: StitchedOos.fromJson(run.stitchedOos ?? const {'net': 0, 'trades': 0, 'days': 0, 'folds': 5, 'positive_folds': 4}),
      folds: folds,
    );
  }

  @override
  Future<SweepDoc> getSweep(String sweepId) async {
    final combos = List.generate(8, (i) {
      final pf = 4.5 - i * 0.3;
      return SweepCombo(
        params: {'hedge_enabled': i.isEven, 'day_loss_limit': 10000 + i * 2500},
        metrics: {'net': 500000.0 - i * 40000, 'profit_factor': pf, 'sharpe': 1.5 - i * 0.1},
        rank: i,
      );
    });
    return SweepDoc(
      sweepId: sweepId,
      kind: 'sweep',
      grid: const {'hedge_enabled': [true, false], 'day_loss_limit': [10000, 12500, 15000, 17500]},
      objective: 'pf',
      combos: combos,
      bestParam: combos.first.params,
      createdAt: DateTime(2026, 7, 1),
    );
  }

  Future<String> _submitFakeJob(String type, {Map<String, dynamic>? resultOnComplete}) async {
    final jobId = 'mock-job-${_jobs.length + 1}';
    _jobs[jobId] = JobRecord(id: jobId, type: type, status: 'PENDING', progress: 0);
    unawaited(() async {
      await Future<void>.delayed(const Duration(milliseconds: 50));
      _jobs[jobId] = JobRecord(id: jobId, type: type, status: 'RUNNING', progress: 60, progressMessage: 'Running $type');
      await Future<void>.delayed(const Duration(milliseconds: 150));
      _jobs[jobId] = JobRecord(
        id: jobId, type: type, status: 'COMPLETED', progress: 100,
        progressMessage: 'Completed', result: resultOnComplete,
      );
    }());
    return jobId;
  }

  @override
  Future<String> launchSingle(Map<String, dynamic> request) async {
    final runId = 'strangle_${DateTime.now().millisecondsSinceEpoch}';
    _runs.insert(
      0,
      BacktestRun(
        runId: runId, kind: 'single', strategyId: 'strangle', canonicalStrategyId: 'directional_strangle_nifty',
        verdict: null, createdAt: DateTime.now(), metrics: const {}, config: request['config'] as Map<String, dynamic>? ?? const {},
        status: 'complete', promotionState: 'none',
      ),
    );
    return _submitFakeJob('backtest:single', resultOnComplete: {'run_id': runId});
  }

  @override
  Future<String> launchSweep(Map<String, dynamic> request) async {
    return _submitFakeJob('backtest:sweep', resultOnComplete: {'sweep_id': 'sweep-${DateTime.now().millisecondsSinceEpoch}'});
  }

  @override
  Future<String> launchWalkforward(Map<String, dynamic> request) async {
    final runId = 'strangle_wf_${DateTime.now().millisecondsSinceEpoch}';
    return _submitFakeJob('backtest:walkforward', resultOnComplete: {'run_id': runId});
  }

  @override
  Future<void> promoteRun(String runId, {String? note}) async {
    final idx = _runs.indexWhere((r) => r.runId == runId);
    if (idx == -1) throw StateError('run not found: $runId');
    final run = _runs[idx];
    _runs[idx] = BacktestRun(
      runId: run.runId, kind: run.kind, strategyId: run.strategyId, canonicalStrategyId: run.canonicalStrategyId,
      verdict: run.verdict, createdAt: run.createdAt, metrics: run.metrics, config: run.config,
      status: run.status, promotionState: 'promoted', gitSha: run.gitSha, stitchedOos: run.stitchedOos, window: run.window,
    );
  }

  @override
  Future<PromotionEvidence> getPromotionEvidence(String runId) async {
    return PromotionEvidence(
      runId: 'promo_$runId', sourceRunId: runId, strategyId: 'directional_strangle_nifty',
      yamlPath: 'backend/pdp/strategies/directional_strangle_nifty.yaml', verdict: 'PASS',
      stitchedOos: const {'net': 856000.0, 'profit_factor': 5.72, 'sharpe': 1.8, 'trades': 412, 'days': 620, 'folds': 1, 'positive_folds': 1},
      verdictBreakdown: const VerdictBreakdown(
        checks: {
          'net': VerdictCheck(actual: 856000, threshold: 0, pass: true),
          'profit_factor': VerdictCheck(actual: 5.72, threshold: 1.2, pass: true),
          'sharpe': VerdictCheck(actual: 1.8, threshold: 0.5, pass: true),
          'positive_fold_fraction': VerdictCheck(actual: 1.0, threshold: 0.6, pass: true),
        },
        allPass: true, positiveFolds: 1, folds: 1,
      ),
      note: null,
      promotedAt: DateTime(2026, 7, 1, 9, 45),
    );
  }

  @override
  Future<VsPaperDayResult> getVsPaperDay(String runId) async {
    final equity = await getEquity(runId);
    return VsPaperDayResult(
      runId: runId, strategyId: 'directional_strangle_nifty', paperDataAvailable: true,
      days: equity.take(10).map((e) {
        final paperNet = e.net * (0.9 + _rng.nextDouble() * 0.2);
        final divergence = (e.net - paperNet).abs();
        return DayDivergence(
          date: e.date, backtestNet: e.net, paperNet: paperNet,
          divergence: divergence, diverges: divergence > 4000, cause: divergence > 4000 ? 'slippage' : null,
        );
      }).toList(growable: false),
    );
  }

  @override
  Future<VsPaperMinuteResult> getVsPaperMinute(String runId, String date) async {
    return VsPaperMinuteResult(
      runId: runId, strategyId: 'directional_strangle_nifty', date: date,
      minutes: [
        MinuteBucket(
          minute: '$date 09:20',
          backtest: [MinuteSideEvent(side: 'backtest', tsIst: '$date 09:20:03', minute: '09:20', action: 'entry')],
          live: [MinuteSideEvent(side: 'live', tsIst: '$date 09:20:41', minute: '09:20', action: 'entry')],
          mismatch: false,
        ),
        MinuteBucket(
          minute: '$date 12:05',
          backtest: [MinuteSideEvent(side: 'backtest', tsIst: '$date 12:05:00', minute: '12:05', action: 'scale_in')],
          live: const [],
          mismatch: true,
          cause: 'live missed scale-in signal window',
        ),
      ],
    );
  }

  @override
  Future<CoverageResponse> getCoverage({String? from, String? to, String? underlying}) async {
    UnderlyingCoverage build(String u) {
      final family = FamilyCoverage.fromJson({
        'min_date': '2026-01-01', 'max_date': '2026-06-30', 'covered_days': 118, 'total_days': 120,
        'coverage_pct': 98.3, 'gap_ranges': [['2026-03-14', '2026-03-15']],
      });
      final futures = FamilyCoverage.fromJson({
        'min_date': null, 'max_date': null, 'covered_days': 0, 'total_days': 120, 'coverage_pct': 0.0,
        'gap_ranges': [], 'status': 'unavailable', 'note': 'futures source not yet ingested',
      });
      return UnderlyingCoverage(
        underlying: u,
        families: {'spot': family, 'options': family, 'vix': family, 'levels_daily': family, 'levels_weekly': family, 'futures': futures},
        radar: {
          '2026-03-14': {'spot': 'spot/VWAP missing', 'options': 'ready', 'vix': 'ready', 'levels_weekly': 'ready', 'futures': 'futures missing'},
          '2026-03-15': {'spot': 'ready', 'options': 'ready', 'vix': 'VIX missing', 'levels_weekly': 'ready', 'futures': 'futures missing'},
        },
      );
    }

    final all = {'NIFTY': build('NIFTY'), 'BANKNIFTY': build('BANKNIFTY'), 'SENSEX': build('SENSEX')};
    return CoverageResponse(
      from: from ?? '2026-01-01',
      to: to ?? '2026-06-30',
      underlyings: underlying != null ? {underlying: all[underlying]!} : all,
    );
  }

  @override
  Future<String> runHousekeeping(String taskName, Map<String, dynamic> params) async {
    return _submitFakeJob('housekeeping:$taskName');
  }

  @override
  Future<List<StrategyInfo>> getStrategies() async {
    return [
      const StrategyInfo(
        id: 'directional_strangle_nifty', kind: 'strangle', underlying: 'NIFTY', source: 'live', status: 'RUNNING',
        paramsSchema: [
          ParamSpec(name: 'st_period', type: 'int', defaultValue: 10, min: 5, max: 30),
          ParamSpec(name: 'st_multiplier', type: 'float', defaultValue: 2.0, min: 1.0, max: 5.0),
          ParamSpec(name: 'timeframe_min', type: 'int', defaultValue: 15, min: 1, max: 60),
          ParamSpec(name: 'hedge_enabled', type: 'bool', defaultValue: true),
        ],
        defaults: {'st_period': 10, 'st_multiplier': 2.0, 'timeframe_min': 15, 'hedge_enabled': true},
      ),
      const StrategyInfo(
        id: 'directional_strangle_banknifty', kind: 'strangle', underlying: 'BANKNIFTY', source: 'backtest', status: 'BACKTEST_ONLY',
        paramsSchema: [
          ParamSpec(name: 'st_period', type: 'int', defaultValue: 10, min: 5, max: 30),
          ParamSpec(name: 'st_multiplier', type: 'float', defaultValue: 2.0, min: 1.0, max: 5.0),
        ],
        defaults: {'st_period': 10, 'st_multiplier': 2.0},
      ),
    ];
  }

  @override
  Future<JobRecord> getJob(String jobId) async {
    return _jobs[jobId] ?? JobRecord(id: jobId, type: 'unknown', status: 'PENDING', progress: 0);
  }

  @override
  Stream<JobProgress> watchJob(String jobId) async* {
    while (true) {
      await Future<void>.delayed(const Duration(milliseconds: 40));
      final job = _jobs[jobId];
      if (job == null) continue;
      yield JobProgress(progress: job.progress, message: job.progressMessage ?? '');
      if (job.isTerminal) break;
    }
  }
}
