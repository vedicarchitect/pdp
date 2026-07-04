import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../shared/widgets/pnl_text.dart';
import '../application/backtest_providers.dart';
import '../domain/models.dart';
import 'widgets/day_table.dart';
import 'widgets/decision_trace_panel.dart';
import 'widgets/equity_drawdown_chart.dart';
import 'widgets/export_menu.dart';
import 'widgets/fold_panel.dart';
import 'widgets/promote_dialog.dart';
import 'widgets/status_chips.dart';
import 'widgets/vs_paper_view.dart';

class BacktestDetailScreen extends ConsumerWidget {
  const BacktestDetailScreen({super.key, required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detailAsync = ref.watch(backtestRunDetailProvider(runId));

    return Scaffold(
      appBar: AppBar(
        title: Text(runId, overflow: TextOverflow.ellipsis),
        actions: [
          detailAsync.maybeWhen(
            data: (run) => run.verdict == 'PASS' && !run.isPromoted
                ? Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: FilledButton.icon(
                      onPressed: () => showDialog<void>(
                        context: context,
                        builder: (context) => PromoteDialog(run: run),
                      ),
                      icon: const Icon(Icons.rocket_launch, size: 18),
                      label: const Text('Promote'),
                    ),
                  )
                : const SizedBox.shrink(),
            orElse: () => const SizedBox.shrink(),
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(backtestRunDetailProvider(runId));
              ref.invalidate(backtestEquityProvider(runId));
              ref.invalidate(backtestDaysProvider(runId));
            },
          ),
        ],
      ),
      body: detailAsync.when(
        data: (run) => _DetailBody(run: run),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
      ),
    );
  }
}

class _DetailBody extends ConsumerWidget {
  const _DetailBody({required this.run});

  final BacktestRun run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tabs = <Tab>[
      const Tab(text: 'Overview'),
      const Tab(text: 'Days'),
      const Tab(text: 'Decisions'),
      if (run.isWalkforward) const Tab(text: 'Folds'),
      const Tab(text: 'Paper'),
    ];
    final views = <Widget>[
      _OverviewTab(run: run),
      _DaysTab(runId: run.runId),
      _DecisionsTab(runId: run.runId),
      if (run.isWalkforward) _FoldsTab(runId: run.runId),
      VsPaperView(runId: run.runId),
    ];

    return DefaultTabController(
      length: tabs.length,
      child: Column(
        children: [
          TabBar(tabs: tabs, isScrollable: true),
          Expanded(child: TabBarView(children: views)),
        ],
      ),
    );
  }
}

class _OverviewTab extends ConsumerWidget {
  const _OverviewTab({required this.run});

  final BacktestRun run;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final equityAsync = ref.watch(backtestEquityProvider(run.runId));

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          flex: 1,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [VerdictChip(run.verdict), const SizedBox(width: 8), Text(run.kind)]),
                const SizedBox(height: 16),
                Text('Metrics', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                _metricRow('Net', '-', pnl: run.net),
                _metricRow('Profit factor', run.profitFactor?.toStringAsFixed(2) ?? '-'),
                _metricRow('Sharpe', run.sharpe?.toStringAsFixed(2) ?? '-'),
                _metricRow('Max drawdown', run.maxDd != null ? '₹${run.maxDd!.toStringAsFixed(0)}' : '-'),
                _metricRow('Win rate', run.winRate != null ? '${(run.winRate! * 100).toStringAsFixed(1)}%' : '-'),
                _metricRow('Calmar', run.calmar?.toStringAsFixed(2) ?? '-'),
                _metricRow('Trades', run.trades?.toString() ?? '-'),
                if (run.window != null) _metricRow('Window', '${run.window!.from} → ${run.window!.to}'),
                const Divider(height: 32),
                Text('Config', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(run.config.toString(), style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
              ],
            ),
          ),
        ),
        const VerticalDivider(width: 1),
        Expanded(
          flex: 2,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: equityAsync.when(
              data: (equity) => EquityDrawdownChart(equity: equity),
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
            ),
          ),
        ),
      ],
    );
  }

  Widget _metricRow(String label, String? value, {double? pnl}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: AppColors.textMuted),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerRight,
              child: pnl != null ? PnlText(pnl) : Text(value ?? '-'),
            ),
          ),
        ],
      ),
    );
  }
}

class _DaysTab extends ConsumerWidget {
  const _DaysTab({required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final daysAsync = ref.watch(backtestDaysProvider(runId));

    return daysAsync.when(
      data: (days) => Column(
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: ExportButton(
                filenamePrefix: '${runId}_days',
                rows: days
                    .map((d) => {
                          'date': d.date, 'net': d.net, 'cum_equity': d.cumEquity, 'drawdown': d.drawdown,
                          'trades': d.trades, 'halted': d.halted,
                        })
                    .toList(growable: false),
              ),
            ),
          ),
          Expanded(child: DayTable(runId: runId, days: days)),
        ],
      ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
    );
  }
}

class _DecisionsTab extends ConsumerWidget {
  const _DecisionsTab({required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final daysAsync = ref.watch(backtestDaysProvider(runId));
    return daysAsync.when(
      data: (days) => DecisionTracePanel(runId: runId, dates: days.map((d) => d.date).toList(growable: false)),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
    );
  }
}

class _FoldsTab extends ConsumerWidget {
  const _FoldsTab({required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final foldsAsync = ref.watch(backtestFoldsProvider(runId));
    final equityAsync = ref.watch(backtestEquityProvider(runId));

    return foldsAsync.when(
      data: (folds) => equityAsync.when(
        data: (equity) => FoldPanel(result: folds, stitchedEquity: equity),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
      ),
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
    );
  }
}
