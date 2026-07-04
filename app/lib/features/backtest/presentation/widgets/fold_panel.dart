import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../domain/folds.dart';
import '../../domain/models.dart';
import 'equity_drawdown_chart.dart';
import 'status_chips.dart';

/// Walk-forward per-fold IS-vs-OOS metrics, the stitched-OOS verdict, and the
/// stitched-OOS equity curve (the run's day-by-day equity already IS the
/// stitched-OOS series for a walk-forward run).
class FoldPanel extends StatelessWidget {
  const FoldPanel({super.key, required this.result, required this.stitchedEquity});

  final FoldsResult result;
  final List<EquityPoint> stitchedEquity;

  @override
  Widget build(BuildContext context) {
    final stitched = result.stitchedOos;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              VerdictChip(result.verdict),
              if (stitched != null) ...[
                Text('PF ${stitched.profitFactor?.toStringAsFixed(2) ?? '-'}'),
                Text('Sharpe ${stitched.sharpe?.toStringAsFixed(2) ?? '-'}'),
                PnlText(stitched.net),
                Text('${stitched.positiveFolds}/${stitched.folds} positive folds'),
              ],
            ],
          ),
          const SizedBox(height: 16),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [
                DataColumn(label: Text('Fold')),
                DataColumn(label: Text('IS window')),
                DataColumn(label: Text('OOS window')),
                DataColumn(label: Text('IS PF'), numeric: true),
                DataColumn(label: Text('OOS PF'), numeric: true),
                DataColumn(label: Text('OOS Net'), numeric: true),
                DataColumn(label: Text('OOS Win%'), numeric: true),
              ],
              rows: result.folds.map((fold) {
                return DataRow(
                  color: WidgetStatePropertyAll(
                    (fold.isPositive ? AppColors.profit : AppColors.loss).withValues(alpha: 0.06),
                  ),
                  cells: [
                    DataCell(Text('${fold.foldIndex + 1}')),
                    DataCell(Text('${fold.isWindow.start} → ${fold.isWindow.end}')),
                    DataCell(Text('${fold.oosWindow.start} → ${fold.oosWindow.end}')),
                    DataCell(Text((fold.isMetrics['profit_factor'] as num?)?.toStringAsFixed(2) ?? '-')),
                    DataCell(Text(fold.oosProfitFactor?.toStringAsFixed(2) ?? '-')),
                    DataCell(fold.oosNet != null ? PnlText(fold.oosNet!) : const Text('-')),
                    DataCell(Text(
                      (((fold.oosMetrics['win_rate'] as num?)?.toDouble() ?? 0) * 100).toStringAsFixed(1),
                    )),
                  ],
                );
              }).toList(growable: false),
            ),
          ),
          const SizedBox(height: 16),
          Text('Stitched-OOS equity', style: Theme.of(context).textTheme.titleSmall),
          Expanded(child: EquityDrawdownChart(equity: stitchedEquity)),
        ],
      ),
    );
  }
}
