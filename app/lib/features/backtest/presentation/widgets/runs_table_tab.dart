import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/backtest_providers.dart';
import '../../domain/models.dart';
import 'status_chips.dart';

const _sortOptions = {
  'created_at': 'Date',
  'pf': 'Profit factor',
  'net': 'Net',
  'sharpe': 'Sharpe',
  'max_dd': 'Max DD',
};

const _underlyings = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

/// The backend filters runs by kind/strategy_id/verdict only — there is no
/// underlying filter, so the index selector is applied client-side against
/// the run's config/canonical id.
bool _matchesUnderlying(BacktestRun run, String underlying) {
  final configUnderlying = (run.config['underlying'] as String?)?.toUpperCase();
  if (configUnderlying == underlying) return true;
  final canonical = run.canonicalStrategyId?.toUpperCase() ?? '';
  return canonical.contains(underlying);
}

/// The run-history table: filter by kind/verdict, sort by metric, verdict +
/// promotion chips, and an all-index (strategy) selector.
class RunsTableTab extends ConsumerWidget {
  const RunsTableTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runsAsync = ref.watch(backtestRunsProvider);
    final filter = ref.watch(runsFilterProvider);
    final notifier = ref.read(runsFilterProvider.notifier);
    final dateFormat = DateFormat('yyyy-MM-dd HH:mm');

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    DropdownButton<String?>(
                      value: filter.kind,
                      hint: const Text('All kinds'),
                      items: const [
                        DropdownMenuItem(value: null, child: Text('All kinds')),
                        DropdownMenuItem(
                            value: 'single', child: Text('Single')),
                        DropdownMenuItem(value: 'sweep', child: Text('Sweep')),
                        DropdownMenuItem(
                            value: 'walkforward', child: Text('Walk-forward')),
                      ],
                      onChanged: (v) =>
                          notifier.update((f) => f.copyWith(kind: () => v)),
                    ),
                    DropdownButton<String?>(
                      value: filter.verdict,
                      hint: const Text('All verdicts'),
                      items: const [
                        DropdownMenuItem(
                            value: null, child: Text('All verdicts')),
                        DropdownMenuItem(value: 'PASS', child: Text('PASS')),
                        DropdownMenuItem(
                            value: 'REVIEW', child: Text('REVIEW')),
                      ],
                      onChanged: (v) =>
                          notifier.update((f) => f.copyWith(verdict: () => v)),
                    ),
                    DropdownButton<String?>(
                      value: filter.underlying,
                      hint: const Text('All indices'),
                      items: [
                        const DropdownMenuItem(
                            value: null, child: Text('All indices')),
                        ..._underlyings.map(
                            (u) => DropdownMenuItem(value: u, child: Text(u))),
                      ],
                      onChanged: (v) => notifier
                          .update((f) => f.copyWith(underlying: () => v)),
                    ),
                    DropdownButton<String>(
                      value: filter.sortBy,
                      items: _sortOptions.entries
                          .map((e) => DropdownMenuItem(
                              value: e.key, child: Text('Sort: ${e.value}')))
                          .toList(growable: false),
                      onChanged: (v) =>
                          notifier.update((f) => f.copyWith(sortBy: v)),
                    ),
                    IconButton(
                      tooltip: filter.sortDir < 0 ? 'Descending' : 'Ascending',
                      icon: Icon(filter.sortDir < 0
                          ? Icons.arrow_downward
                          : Icons.arrow_upward),
                      onPressed: () => notifier
                          .update((f) => f.copyWith(sortDir: -f.sortDir)),
                    ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: () => ref.invalidate(backtestRunsProvider),
              ),
            ],
          ),
        ),
        Expanded(
          child: runsAsync.when(
            data: (page) {
              final runs = filter.underlying == null
                  ? page.runs
                  : page.runs
                      .where((r) => _matchesUnderlying(r, filter.underlying!))
                      .toList(growable: false);
              if (runs.isEmpty) {
                return const Center(child: Text('No backtest runs found.'));
              }
              return SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columns: const [
                      DataColumn(label: Text('Run ID')),
                      DataColumn(label: Text('Kind')),
                      DataColumn(label: Text('Strategy')),
                      DataColumn(label: Text('Verdict')),
                      DataColumn(label: Text('Promotion')),
                      DataColumn(label: Text('PF'), numeric: true),
                      DataColumn(label: Text('Sharpe'), numeric: true),
                      DataColumn(label: Text('Net'), numeric: true),
                      DataColumn(label: Text('Max DD'), numeric: true),
                      DataColumn(label: Text('Date')),
                    ],
                    rows: runs.map((run) {
                      return DataRow(
                        onSelectChanged: (_) =>
                            context.go('/backtests/${run.runId}'),
                        cells: [
                          DataCell(Text(run.runId.length > 22
                              ? '${run.runId.substring(0, 22)}…'
                              : run.runId)),
                          DataCell(Text(run.kind)),
                          DataCell(Text(run.canonicalStrategyId ??
                              run.strategyId ??
                              '—')),
                          DataCell(VerdictChip(run.verdict)),
                          DataCell(run.isPromoted
                              ? const StatusChip('PROMOTED',
                                  color: AppColors.profit)
                              : const StatusChip('—',
                                  color: AppColors.neutral)),
                          DataCell(Text(
                              run.profitFactor?.toStringAsFixed(2) ?? '-')),
                          DataCell(Text(run.sharpe?.toStringAsFixed(2) ?? '-')),
                          DataCell(
                              PnlText(run.net ?? 0, showSign: run.net != null)),
                          DataCell(Text(run.maxDd != null
                              ? '₹${run.maxDd!.toStringAsFixed(0)}'
                              : '-')),
                          DataCell(
                              Text(dateFormat.format(run.createdAt.toLocal()))),
                        ],
                      );
                    }).toList(growable: false),
                  ),
                ),
              );
            },
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, _) => Center(
                child: Text('Error: $err',
                    style: const TextStyle(color: AppColors.loss))),
          ),
        ),
      ],
    );
  }
}
