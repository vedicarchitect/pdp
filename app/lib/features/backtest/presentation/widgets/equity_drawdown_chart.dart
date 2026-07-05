import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../domain/models.dart';

/// Dual-series equity (cumulative) + drawdown chart, sharing a date axis.
class EquityDrawdownChart extends StatelessWidget {
  const EquityDrawdownChart({super.key, required this.equity});

  final List<EquityPoint> equity;

  @override
  Widget build(BuildContext context) {
    if (equity.isEmpty) {
      return const Center(child: Text('No equity data'));
    }

    final equitySpots = <FlSpot>[];
    final drawdownSpots = <FlSpot>[];
    for (var i = 0; i < equity.length; i++) {
      equitySpots.add(FlSpot(i.toDouble(), equity[i].cumEquity));
      drawdownSpots.add(FlSpot(i.toDouble(), equity[i].drawdown));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Equity', style: Theme.of(context).textTheme.titleSmall?.copyWith(color: AppColors.profit)),
        Expanded(
          flex: 3,
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: LineChart(
              LineChartData(
                lineBarsData: [
                  LineChartBarData(
                    spots: equitySpots,
                    isCurved: false,
                    color: AppColors.profit,
                    barWidth: 2,
                    dotData: const FlDotData(show: false),
                    belowBarData: BarAreaData(show: true, color: AppColors.profitFaint),
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
        const SizedBox(height: 12),
        Text('Drawdown', style: Theme.of(context).textTheme.titleSmall?.copyWith(color: AppColors.loss)),
        Expanded(
          flex: 2,
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: LineChart(
              LineChartData(
                lineBarsData: [
                  LineChartBarData(
                    spots: drawdownSpots,
                    isCurved: false,
                    color: AppColors.loss,
                    barWidth: 2,
                    dotData: const FlDotData(show: false),
                    belowBarData: BarAreaData(show: true, color: AppColors.lossFaint),
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
      ],
    );
  }
}
