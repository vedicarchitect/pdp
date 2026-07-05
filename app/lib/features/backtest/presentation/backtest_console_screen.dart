import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../application/backtest_providers.dart';
import 'widgets/coverage_tab.dart';
import 'widgets/dashboard_links.dart';
import 'widgets/export_menu.dart';
import 'widgets/launch_backtest_dialog.dart';
import 'widgets/runs_table_tab.dart';
import 'widgets/sweep_tab.dart';

class BacktestConsoleScreen extends ConsumerWidget {
  const BacktestConsoleScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Backtest Console'),
          bottom: const TabBar(
            tabs: [
              Tab(text: 'Runs'),
              Tab(text: 'Sweeps'),
              Tab(text: 'Coverage'),
            ],
          ),
          actions: [
            Consumer(
              builder: (context, ref, _) {
                final runs = ref.watch(backtestRunsProvider).valueOrNull?.runs ?? const [];
                return ExportButton(
                  filenamePrefix: 'backtest_runs',
                  rows: runs
                      .map((r) => {
                            'run_id': r.runId,
                            'kind': r.kind,
                            'strategy_id': r.canonicalStrategyId ?? r.strategyId,
                            'verdict': r.verdict,
                            'net': r.net,
                            'profit_factor': r.profitFactor,
                            'sharpe': r.sharpe,
                            'max_dd': r.maxDd,
                            'created_at': r.createdAt.toIso8601String(),
                          })
                      .toList(growable: false),
                );
              },
            ),
            const DashboardLinksButton(),
            const SizedBox(width: 8),
          ],
        ),
        body: const TabBarView(
          children: [
            RunsTableTab(),
            SweepTab(),
            CoverageTab(),
          ],
        ),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: () => showDialog<void>(
            context: context,
            builder: (context) => const LaunchBacktestDialog(),
          ),
          icon: const Icon(Icons.add),
          label: const Text('New Run'),
        ),
      ),
    );
  }
}
