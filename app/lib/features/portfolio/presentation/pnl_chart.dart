import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../application/portfolio_providers.dart';

/// A minimal day-P&L sparkline. Placeholder for a richer equity/candle chart;
/// renders the rolling [pnlHistoryProvider] window with fl_chart.
class PnlChart extends ConsumerWidget {
  const PnlChart({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final history = ref.watch(pnlHistoryProvider);

    return Container(
      height: 140,
      padding: const EdgeInsets.fromLTRB(12, 16, 16, 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: history.length < 2
          ? const Center(
              child: Text(
                'Charting day P&L…',
                style: TextStyle(color: AppColors.textMuted),
              ),
            )
          : LineChart(_chartData(history)),
    );
  }

  LineChartData _chartData(List<double> values) {
    final last = values.last;
    final positive = last >= 0;
    final color = positive ? AppColors.profit : AppColors.loss;
    final fill = positive ? AppColors.profitFaint : AppColors.lossFaint;

    var minY = values.reduce((a, b) => a < b ? a : b);
    var maxY = values.reduce((a, b) => a > b ? a : b);
    if (minY == maxY) {
      minY -= 1;
      maxY += 1;
    }
    final pad = (maxY - minY) * 0.15;

    return LineChartData(
      gridData: const FlGridData(show: false),
      titlesData: const FlTitlesData(show: false),
      borderData: FlBorderData(show: false),
      lineTouchData: const LineTouchData(enabled: false),
      minY: minY - pad,
      maxY: maxY + pad,
      lineBarsData: [
        LineChartBarData(
          spots: [
            for (var i = 0; i < values.length; i++)
              FlSpot(i.toDouble(), values[i]),
          ],
          isCurved: true,
          color: color,
          barWidth: 2,
          dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(show: true, color: fill),
        ),
      ],
    );
  }
}
