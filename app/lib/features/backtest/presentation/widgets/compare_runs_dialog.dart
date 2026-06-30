import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';
import '../../application/backtest_providers.dart';

final backtestCompareProvider = FutureProvider.family.autoDispose<List<dynamic>, List<String>>((ref, runIds) async {
  final repo = ref.watch(backtestRepositoryProvider);
  return repo.compareRuns(runIds);
});

class CompareRunsDialog extends ConsumerWidget {
  const CompareRunsDialog({super.key, required this.runIds});
  final List<String> runIds;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final compareAsync = ref.watch(backtestCompareProvider(runIds));

    return Dialog(
      child: Container(
        width: 800,
        height: 600,
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Compare Runs', style: Theme.of(context).textTheme.headlineSmall),
                IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.of(context).pop()),
              ],
            ),
            const SizedBox(height: 24),
            Expanded(
              child: compareAsync.when(
                data: (results) {
                  final colors = [
                    Colors.blue,
                    Colors.red,
                    Colors.green,
                    Colors.orange,
                    Colors.purple,
                    Colors.teal,
                    Colors.amber,
                  ];
                  
                  return Column(
                    children: [
                      // Legend
                      Wrap(
                        spacing: 16,
                        children: results.asMap().entries.map((e) {
                          final run = e.value;
                          final color = colors[e.key % colors.length];
                          return Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Container(width: 12, height: 12, color: color),
                              const SizedBox(width: 4),
                              Text(run.runId.toString().substring(0, 8)),
                            ],
                          );
                        }).toList(),
                      ),
                      const SizedBox(height: 24),
                      Expanded(
                        child: LineChart(
                          LineChartData(
                            lineBarsData: results.asMap().entries.map((e) {
                              final run = e.value;
                              final equity = run.equity;
                              final points = <FlSpot>[];
                              for (int i = 0; i < equity.length; i++) {
                                points.add(FlSpot(i.toDouble(), equity[i].cumEquity));
                              }
                              return LineChartBarData(
                                spots: points,
                                isCurved: false,
                                color: colors[e.key % colors.length],
                                barWidth: 2,
                                dotData: const FlDotData(show: false),
                              );
                            }).toList(),
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
                  );
                },
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (err, stack) => Center(child: Text('Error: $err')),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
