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

// Must match the backend's UNDERLYING_REGISTRY (pdp/warehouse/service.py) — an
// index added here with no backend/warehouse support renders a permanently
// empty tab and leaderboard card.
const _underlyings = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

/// The index selector is applied client-side against the run's top-level
/// `underlying` field (falling back to `config.underlying` for older docs
/// predating the backfill). Do NOT substring-match against
/// `canonicalStrategyId` — "BANKNIFTY" contains "NIFTY", so that fallback
/// used to put BANKNIFTY runs under the NIFTY tab too.
bool _matchesUnderlying(BacktestRun run, String underlying) {
  final runUnderlying =
      (run.underlying ?? run.config['underlying'] as String?)?.toUpperCase();
  return runUnderlying == underlying;
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
          child: DefaultTabController(
            length: _underlyings.length,
            child: Column(
              children: [
                TabBar(
                  isScrollable: true,
                  tabs: _underlyings.map((u) => Tab(text: u)).toList(),
                ),
                Expanded(
                  child: TabBarView(
                    children: _underlyings.map((u) {
                      return _UnderlyingTabContent(
                        underlying: u,
                        runsAsync: runsAsync,
                        filter: filter,
                        dateFormat: dateFormat,
                      );
                    }).toList(),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _UnderlyingTabContent extends ConsumerWidget {
  const _UnderlyingTabContent({
    required this.underlying,
    required this.runsAsync,
    required this.filter,
    required this.dateFormat,
  });

  final String underlying;
  final AsyncValue<RunsPage> runsAsync;
  final RunsFilter filter;
  final DateFormat dateFormat;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        _LeaderboardCard(underlying: underlying),
        Expanded(
          child: runsAsync.when(
            data: (page) {
              final runs = page.runs
                  .where((r) => _matchesUnderlying(r, underlying))
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
                            context.go('/backtests/${run.kind}/${run.runId}'),
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

class _LeaderboardCard extends ConsumerWidget {
  const _LeaderboardCard({required this.underlying});

  final String underlying;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lbAsync = ref.watch(backtestLeaderboardProvider);

    return lbAsync.when(
      data: (lbMap) {
        final entry = lbMap[underlying];
        if (entry == null) return const SizedBox.shrink();

        final statusText = entry.promotionState == 'promoted'
            ? 'is currently trading live'
            : (entry.verdict == 'PASS' ? 'is ready to trade' : 'needs review');

        return Card(
          margin: const EdgeInsets.all(12),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Icon(Icons.emoji_events, color: Colors.amber, size: 32),
                const SizedBox(width: 16),
                Expanded(
                  child: Text.rich(
                    TextSpan(
                      children: [
                        const TextSpan(text: 'The best performer is '),
                        TextSpan(
                          text: entry.id.length > 15 ? '${entry.id.substring(0, 15)}…' : entry.id,
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        const TextSpan(text: ' yielding '),
                        TextSpan(
                          text: '₹${entry.net.toStringAsFixed(0)}',
                          style: const TextStyle(fontWeight: FontWeight.bold, color: AppColors.profit),
                        ),
                        TextSpan(text: ' over ${entry.days} days. '),
                        TextSpan(text: 'This config $statusText.'),
                      ],
                    ),
                  ),
                ),
                VerdictChip(entry.verdict),
                const SizedBox(width: 8),
                if (entry.promotionState == 'promoted')
                  const StatusChip('PROMOTED', color: AppColors.profit),
              ],
            ),
          ),
        );
      },
      loading: () => const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator())),
      error: (err, _) => const SizedBox.shrink(),
    );
  }
}
