import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import '../application/backtest_providers.dart';
import 'widgets/compare_runs_dialog.dart';
import 'widgets/launch_backtest_dialog.dart';

class BacktestConsoleScreen extends ConsumerStatefulWidget {
  const BacktestConsoleScreen({super.key});

  @override
  ConsumerState<BacktestConsoleScreen> createState() => _BacktestConsoleScreenState();
}

class _BacktestConsoleScreenState extends ConsumerState<BacktestConsoleScreen> {
  final Set<String> _selectedRuns = {};

  @override
  Widget build(BuildContext context) {
    final runsAsync = ref.watch(backtestRunsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Backtest Console'),
        actions: [
          if (_selectedRuns.isNotEmpty)
            FilledButton.icon(
              onPressed: () {
                showDialog<void>(
                  context: context,
                  builder: (context) => CompareRunsDialog(runIds: _selectedRuns.toList()),
                );
              },
              icon: const Icon(Icons.compare_arrows),
              label: Text('Compare (${_selectedRuns.length})'),
            ),
          const SizedBox(width: 8),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              setState(() => _selectedRuns.clear());
              ref.invalidate(backtestRunsProvider);
            },
          ),
        ],
      ),
      body: runsAsync.when(
        data: (runs) {
          if (runs.isEmpty) {
            return const Center(child: Text('No backtest runs found.'));
          }
          return SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Card(
                clipBehavior: Clip.antiAlias,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    showCheckboxColumn: true,
                    columns: const [
                      DataColumn(label: Text('Run ID')),
                      DataColumn(label: Text('Kind')),
                      DataColumn(label: Text('Verdict')),
                      DataColumn(label: Text('Profit Factor')),
                      DataColumn(label: Text('Sharpe')),
                      DataColumn(label: Text('Max DD')),
                      DataColumn(label: Text('Date')),
                      DataColumn(label: Text('Action')),
                    ],
                    rows: runs.map((run) {
                      final pf = run.metrics['profit_factor'] as num?;
                      final sharpe = run.metrics['sharpe'] as num?;
                      final maxDd = run.metrics['max_dd'] as num?;
                      final formatter = DateFormat('yyyy-MM-dd HH:mm');
                      
                      return DataRow(
                        selected: _selectedRuns.contains(run.runId),
                        onSelectChanged: (selected) {
                          setState(() {
                            if (selected == true) {
                              _selectedRuns.add(run.runId);
                            } else {
                              _selectedRuns.remove(run.runId);
                            }
                          });
                        },
                        cells: [
                          DataCell(Text(run.runId.length >= 8 ? run.runId.substring(0, 8) : run.runId)),
                          DataCell(Text(run.kind)),
                          DataCell(
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                              decoration: BoxDecoration(
                                color: run.verdict == 'PASS' ? Colors.green.withValues(alpha: 0.2) : Colors.grey.withValues(alpha: 0.2),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(run.verdict ?? 'NONE'),
                            ),
                          ),
                          DataCell(Text(pf?.toStringAsFixed(2) ?? '-')),
                          DataCell(Text(sharpe?.toStringAsFixed(2) ?? '-')),
                          DataCell(Text(maxDd?.toStringAsFixed(2) ?? '-')),
                          DataCell(Text(formatter.format(run.createdAt.toLocal()))),
                          DataCell(
                            TextButton(
                              onPressed: () => context.go('/backtests/${run.runId}'),
                              child: const Text('View'),
                            ),
                          ),
                        ],
                      );
                    }).toList(),
                  ),
                ),
              ),
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text('Error: $err')),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          showDialog<void>(
            context: context,
            builder: (context) => const LaunchBacktestDialog(),
          );
        },
        icon: const Icon(Icons.add),
        label: const Text('New Run'),
      ),
    );
  }
}
