import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/backtest_providers.dart';
import '../../domain/models.dart';

/// Day-by-day P&L table with an expandable trade drill-down per row.
class DayTable extends StatelessWidget {
  const DayTable({super.key, required this.runId, required this.days});

  final String runId;
  final List<BacktestDay> days;

  @override
  Widget build(BuildContext context) {
    if (days.isEmpty) {
      return const Center(child: Text('No days recorded for this run.'));
    }
    return ListView.builder(
      itemCount: days.length,
      itemBuilder: (context, index) {
        final day = days[index];
        return _DayRow(runId: runId, day: day);
      },
    );
  }
}

class _DayRow extends ConsumerWidget {
  const _DayRow({required this.runId, required this.day});

  final String runId;
  final BacktestDay day;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ExpansionTile(
      title: Row(
        children: [
          SizedBox(width: 100, child: Text(day.date)),
          const SizedBox(width: 12),
          Text('${day.trades} trades', style: const TextStyle(color: AppColors.textMuted)),
          const Spacer(),
          if (day.halted.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Text(day.halted, style: const TextStyle(color: AppColors.warning, fontSize: 12)),
            ),
          PnlText(day.net),
        ],
      ),
      children: [
        Consumer(
          builder: (context, ref, _) {
            final tradesAsync = ref.watch(backtestTradesProvider((runId: runId, date: day.date)));
            return tradesAsync.when(
              data: (fills) {
                if (fills.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text('No fills for this day.'),
                  );
                }
                return SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columns: const [
                      DataColumn(label: Text('Time')),
                      DataColumn(label: Text('Side')),
                      DataColumn(label: Text('Type')),
                      DataColumn(label: Text('Strike'), numeric: true),
                      DataColumn(label: Text('Qty'), numeric: true),
                      DataColumn(label: Text('Price'), numeric: true),
                      DataColumn(label: Text('Leg P&L'), numeric: true),
                      DataColumn(label: Text('Day P&L'), numeric: true),
                      DataColumn(label: Text('Note')),
                    ],
                    rows: fills.map((f) {
                      return DataRow(cells: [
                        DataCell(Text(f.time)),
                        DataCell(Text(f.side)),
                        DataCell(Text(f.optType)),
                        DataCell(Text(f.strike.toStringAsFixed(0))),
                        DataCell(Text('${f.qty}')),
                        DataCell(Text(f.price.toStringAsFixed(2))),
                        DataCell(f.legPnl != null ? PnlText(f.legPnl!) : const Text('-')),
                        DataCell(PnlText(f.dayPnl)),
                        DataCell(Text(f.note)),
                      ]);
                    }).toList(growable: false),
                  ),
                );
              },
              loading: () => const Padding(
                padding: EdgeInsets.all(12),
                child: LinearProgressIndicator(),
              ),
              error: (err, _) => Padding(
                padding: const EdgeInsets.all(12),
                child: Text('Error: $err', style: const TextStyle(color: AppColors.loss)),
              ),
            );
          },
        ),
      ],
    );
  }
}
