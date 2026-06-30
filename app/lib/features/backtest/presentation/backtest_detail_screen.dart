import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../application/backtest_providers.dart';

class BacktestDetailScreen extends ConsumerWidget {
  const BacktestDetailScreen({super.key, required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detailAsync = ref.watch(backtestRunDetailProvider(runId));
    final equityAsync = ref.watch(backtestRunEquityProvider(runId));

    return Scaffold(
      appBar: AppBar(
        title: Text('Run $runId'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(backtestRunDetailProvider(runId));
              ref.invalidate(backtestRunEquityProvider(runId));
            },
          ),
        ],
      ),
      body: detailAsync.when(
        data: (detail) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                flex: 1,
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Headline Metrics', style: Theme.of(context).textTheme.titleLarge),
                      const SizedBox(height: 16),
                      ...detail.metrics.entries.map((e) => ListTile(
                        title: Text(e.key),
                        trailing: Text(e.value.toString()),
                        dense: true,
                      )),
                      const Divider(),
                      if (detail.verdict == 'PASS') ...[
                        ElevatedButton.icon(
                          onPressed: () async {
                            try {
                              await ref.read(backtestRepositoryProvider).promoteRun(runId);
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Run Promoted!')));
                                ref.invalidate(backtestRunDetailProvider(runId));
                              }
                            } catch (e) {
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
                              }
                            }
                          },
                          icon: const Icon(Icons.check_circle),
                          label: const Text('Promote to Paper'),
                          style: ElevatedButton.styleFrom(backgroundColor: Colors.green, foregroundColor: Colors.white),
                        ),
                        const SizedBox(height: 16),
                      ],
                    ],
                  ),
                ),
              ),
              const VerticalDivider(),
              Expanded(
                flex: 2,
                child: equityAsync.when(
                  data: (equity) {
                    if (equity.isEmpty) {
                      return const Center(child: Text('No equity data'));
                    }
                    final points = <FlSpot>[];
                    for (int i = 0; i < equity.length; i++) {
                      points.add(FlSpot(i.toDouble(), equity[i].cumEquity));
                    }
                    return Padding(
                      padding: const EdgeInsets.all(32.0),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Equity Curve', style: Theme.of(context).textTheme.titleLarge),
                          const SizedBox(height: 16),
                          Expanded(
                            child: LineChart(
                              LineChartData(
                                lineBarsData: [
                                  LineChartBarData(
                                    spots: points,
                                    isCurved: false,
                                    color: Colors.blue,
                                    barWidth: 2,
                                    dotData: const FlDotData(show: false),
                                  ),
                                ],
                                titlesData: const FlTitlesData(
                                  topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                                  rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                                ),
                                borderData: FlBorderData(show: true),
                                gridData: const FlGridData(show: true),
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (err, stack) => Center(child: Text('Equity Error: $err')),
                ),
              ),
            ],
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, stack) => Center(child: Text('Detail Error: $err')),
      ),
    );
  }
}
