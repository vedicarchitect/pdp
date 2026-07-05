import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';
import '../../domain/vs_paper.dart';

/// Backtest-vs-paper comparison: an overlay of cumulative backtest vs paper
/// P&L, a per-day divergence table, and an on-demand minute-level diff for a
/// chosen date.
class VsPaperView extends ConsumerWidget {
  const VsPaperView({super.key, required this.runId});

  final String runId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vsPaperAsync = ref.watch(vsPaperDayProvider(runId));

    return vsPaperAsync.when(
      data: (result) {
        if (!result.paperDataAvailable || result.days.isEmpty) {
          return const Center(child: Text('No paper trades yet for this strategy.'));
        }
        var btCum = 0.0;
        var paperCum = 0.0;
        final btSpots = <FlSpot>[];
        final paperSpots = <FlSpot>[];
        for (var i = 0; i < result.days.length; i++) {
          btCum += result.days[i].backtestNet ?? 0;
          paperCum += result.days[i].paperNet ?? 0;
          btSpots.add(FlSpot(i.toDouble(), btCum));
          paperSpots.add(FlSpot(i.toDouble(), paperCum));
        }

        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  _LegendDot(color: AppColors.profit, label: 'Backtest'),
                  SizedBox(width: 16),
                  _LegendDot(color: AppColors.info, label: 'Paper'),
                ],
              ),
              SizedBox(
                height: 220,
                child: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: LineChart(
                    LineChartData(
                      lineBarsData: [
                        LineChartBarData(
                          spots: btSpots, isCurved: false, color: AppColors.profit, barWidth: 2,
                          dotData: const FlDotData(show: false),
                        ),
                        LineChartBarData(
                          spots: paperSpots, isCurved: false, color: AppColors.info, barWidth: 2,
                          dotData: const FlDotData(show: false),
                        ),
                      ],
                      titlesData: FlTitlesData(
                        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        bottomTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        leftTitles: AxisTitles(
                          sideTitles: SideTitles(
                            showTitles: true,
                            reservedSize: 40,
                            getTitlesWidget: (value, meta) => Text(
                              value.toStringAsFixed(0),
                              style: const TextStyle(fontSize: 9, color: AppColors.textMuted),
                            ),
                          ),
                        ),
                      ),
                      borderData: FlBorderData(show: true, border: Border.all(color: AppColors.border)),
                      gridData: const FlGridData(show: true),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Expanded(
                child: ListView.builder(
                  itemCount: result.days.length,
                  itemBuilder: (context, i) {
                    final day = result.days[i];
                    return ListTile(
                      dense: true,
                      title: Text(day.date),
                      subtitle: Text(
                        'Backtest ${day.backtestNet?.toStringAsFixed(0) ?? '-'} · '
                        'Paper ${day.paperNet?.toStringAsFixed(0) ?? '-'}'
                        '${day.cause != null ? ' · ${day.cause}' : ''}',
                      ),
                      trailing: day.diverges
                          ? const Icon(Icons.warning_amber, color: AppColors.warning)
                          : const Icon(Icons.check, color: AppColors.profit),
                      onTap: () => showDialog<void>(
                        context: context,
                        builder: (context) => _MinuteDiffDialog(runId: runId, date: day.date),
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text(label),
      ],
    );
  }
}

class _MinuteDiffDialog extends ConsumerWidget {
  const _MinuteDiffDialog({required this.runId, required this.date});

  final String runId;
  final String date;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final minuteAsync = ref.watch(vsPaperMinuteProvider((runId: runId, date: date)));

    return Dialog(
      child: SizedBox(
        width: 700,
        height: 500,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Minute diff — $date', style: Theme.of(context).textTheme.titleMedium),
                  IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.of(context).pop()),
                ],
              ),
              const Divider(),
              Expanded(
                child: minuteAsync.when(
                  data: (result) {
                    if (result.minutes.isEmpty) {
                      return const Center(child: Text('No minute-level data for this date.'));
                    }
                    return ListView.builder(
                      itemCount: result.minutes.length,
                      itemBuilder: (context, i) => _MinuteBucketTile(bucket: result.minutes[i]),
                    );
                  },
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MinuteBucketTile extends StatelessWidget {
  const _MinuteBucketTile({required this.bucket});

  final MinuteBucket bucket;

  String _events(List<MinuteSideEvent> events) =>
      events.isEmpty ? '—' : events.map((e) => e.action).join(', ');

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: Icon(
        bucket.mismatch ? Icons.warning_amber : Icons.check_circle_outline,
        color: bucket.mismatch ? AppColors.warning : AppColors.profit,
        size: 18,
      ),
      title: Text(bucket.minute),
      subtitle: Text('BT: ${_events(bucket.backtest)}   |   Live: ${_events(bucket.live)}'
          '${bucket.cause != null ? '\n${bucket.cause}' : ''}'),
      isThreeLine: bucket.cause != null,
    );
  }
}
