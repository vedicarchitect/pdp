/// Positions tab — Kite-style execution monitor.
///
/// Layout (responsive):
///   Wide:  ┌─ index prices (full width) ───────────────────────────┐
///          │ POSITIONS (per-underlying)      │  INDICATOR PANEL     │
///          │  Open/Active table              │  (side split)        │
///          │  Closed table                   │                      │
///   Narrow: same, stacked (indicators below positions).
///
/// Open legs come from the live /monitor snapshot (entry · ltp · P&L · day-hi/lo ·
/// entry reason). Closed trades come from /strangle/trades (entry → exit · P&L ·
/// exit reason). System-placed legs only; manual broker positions live in the
/// Broker (Dhan) tab.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/manage_providers.dart';
import '../../domain/execution_models.dart';
import '../indicator_panel.dart';

const _indexOrder = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

// Below this width the indicator panel stacks under the positions instead of
// docking to the right.
const _splitBreakpoint = 900.0;

class StrategyExecutionTab extends ConsumerWidget {
  const StrategyExecutionTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final monitorAsync = ref.watch(monitorStreamProvider);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(monitorStreamProvider),
      child: monitorAsync.when(
        data: (snap) => _PositionsBody(snap: snap),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _ErrorView(error: err, ref: ref),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final Object error;
  final WidgetRef ref;
  const _ErrorView({required this.error, required this.ref});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.signal_wifi_off, size: 48, color: Colors.orange),
          const SizedBox(height: 12),
          Text('Monitor unavailable', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text('Strategy may not be running',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => ref.invalidate(monitorStreamProvider),
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }
}

class _PositionsBody extends ConsumerWidget {
  final MonitorSnapshot snap;
  const _PositionsBody({required this.snap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final todayStr = DateFormat('yyyy-MM-dd').format(DateTime.now());
    final tradesAsync = ref.watch(strangleTradesProvider(todayStr));
    final trades = tradesAsync.asData?.value;

    final positions = _PositionsColumn(snap: snap, trades: trades);
    final indicators = IndicatorPanel(indicators: snap.indicators);

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= _splitBreakpoint;
        return Column(
          children: [
            _IndexPriceRow(indices: snap.indices),
            const Divider(height: 1),
            Expanded(
              child: wide
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(flex: 3, child: positions),
                        const VerticalDivider(width: 1),
                        SizedBox(width: 440, child: indicators),
                      ],
                    )
                  : ListView(
                      padding: EdgeInsets.zero,
                      children: [
                        positions,
                        const Divider(),
                        SizedBox(height: 360, child: indicators),
                      ],
                    ),
            ),
          ],
        );
      },
    );
  }
}

// ─── Left column: overall status + per-underlying open/closed ────────────────

class _PositionsColumn extends StatelessWidget {
  final MonitorSnapshot snap;
  final StrangleTrades? trades;
  const _PositionsColumn({required this.snap, required this.trades});

  @override
  Widget build(BuildContext context) {
    final unders = <String>{
      ...snap.groups.map((g) => g.underlying),
      ...?trades?.byIndex.keys,
    }.toList()
      ..sort((a, b) {
        final ia = _indexOrder.indexOf(a);
        final ib = _indexOrder.indexOf(b);
        return (ia == -1 ? 99 : ia).compareTo(ib == -1 ? 99 : ib);
      });

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        _OverallStatusBar(snap: snap),
        const SizedBox(height: 8),
        if (unders.isEmpty)
          const _EmptyCard(message: 'No positions today')
        else
          ...unders.map((u) {
            final group = snap.groups.where((g) => g.underlying == u).firstOrNull;
            final rows = trades?.byIndex[u] ?? const [];
            return _UnderlyingSection(
              underlying: u,
              group: group,
              closed: rows.where((r) => !r.open).toList(),
            );
          }),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _OverallStatusBar extends StatelessWidget {
  final MonitorSnapshot snap;
  const _OverallStatusBar({required this.snap});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bkt = snap.bucket ?? '--';
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            _BucketChip(bucket: bkt),
            const SizedBox(width: 8),
            if (snap.score != null)
              Text('Score: ${snap.score!.toStringAsFixed(2)}',
                  style: Theme.of(context).textTheme.bodySmall),
            const Spacer(),
            Text('Day P&L  ', style: Theme.of(context).textTheme.bodySmall),
            PnlText(snap.dayPnl,
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
            const SizedBox(width: 6),
            if (snap.doneForDay)
              Chip(
                label: const Text('DONE'),
                backgroundColor: cs.errorContainer,
                side: BorderSide.none,
              ),
          ],
        ),
      ),
    );
  }
}

// ─── Per-underlying: header + Open table + Closed table ──────────────────────

class _UnderlyingSection extends StatelessWidget {
  final String underlying;
  final UnderlyingGroup? group;
  final List<StrangleTradeRow> closed;

  const _UnderlyingSection({
    required this.underlying,
    required this.group,
    required this.closed,
  });

  @override
  Widget build(BuildContext context) {
    final openLegs = group?.legs ?? const [];
    final bkt = group?.bucket ?? '--';
    final dayPnl = group?.dayPnl ?? 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 4),
          child: Row(
            children: [
              Text(underlying,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(width: 8),
              _BucketChip(bucket: bkt),
              const Spacer(),
              PnlText(dayPnl,
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
            ],
          ),
        ),
        _GroupLabel('Open / Active (${openLegs.length})'),
        if (openLegs.isEmpty)
          const _MutedLine('no open legs')
        else
          _OpenLegsTable(legs: openLegs),
        const SizedBox(height: 6),
        _GroupLabel('Closed today (${closed.length})'),
        if (closed.isEmpty)
          const _MutedLine('no closed trades')
        else
          _ClosedTradesTable(rows: closed),
        const SizedBox(height: 4),
        const Divider(),
      ],
    );
  }
}

class _OpenLegsTable extends StatelessWidget {
  final List<LegRow> legs;
  const _OpenLegsTable({required this.legs});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 46,
        columnSpacing: 12,
        columns: const [
          DataColumn(label: Text('Type')),
          DataColumn(label: Text('Strike'), numeric: true),
          DataColumn(label: Text('Lots'), numeric: true),
          DataColumn(label: Text('Entry'), numeric: true),
          DataColumn(label: Text('LTP'), numeric: true),
          DataColumn(label: Text('P&L'), numeric: true),
          DataColumn(label: Text('Day H'), numeric: true),
          DataColumn(label: Text('Day L'), numeric: true),
          DataColumn(label: Text('Entry reason')),
        ],
        rows: legs.map((leg) {
          final mtm = leg.mtm ?? 0;
          final tag = leg.isHedge ? 'H' : leg.isMomentum ? 'M' : leg.optType;
          final tagColor = leg.optType == 'CE' ? Colors.indigo : Colors.deepOrange;
          return DataRow(cells: [
            DataCell(_Tag(tag: tag, color: tagColor)),
            DataCell(Text(leg.strike.toStringAsFixed(0))),
            DataCell(Text('${leg.lots}')),
            DataCell(Text(leg.entryPrice > 0 ? leg.entryPrice.toStringAsFixed(1) : '—')),
            DataCell(Text(leg.ltp != null ? leg.ltp!.toStringAsFixed(1) : '--')),
            DataCell(Text(
              leg.mtm != null ? leg.mtm!.toStringAsFixed(0) : '--',
              style: TextStyle(
                  color: mtm >= 0 ? AppColors.profit : AppColors.loss,
                  fontWeight: FontWeight.w600),
            )),
            DataCell(Text(leg.dayHigh != null ? leg.dayHigh!.toStringAsFixed(1) : '--')),
            DataCell(Text(leg.dayLow != null ? leg.dayLow!.toStringAsFixed(1) : '--')),
            DataCell(_ReasonNote(text: leg.entryReason)),
          ]);
        }).toList(),
      ),
    );
  }
}

class _ClosedTradesTable extends StatelessWidget {
  final List<StrangleTradeRow> rows;
  const _ClosedTradesTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 46,
        columnSpacing: 12,
        columns: const [
          DataColumn(label: Text('Type')),
          DataColumn(label: Text('Strike'), numeric: true),
          DataColumn(label: Text('Lots'), numeric: true),
          DataColumn(label: Text('Entry'), numeric: true),
          DataColumn(label: Text('Exit'), numeric: true),
          DataColumn(label: Text('P&L'), numeric: true),
          DataColumn(label: Text('Exit reason')),
        ],
        rows: rows.map((r) {
          final pnl = r.pnl ?? 0;
          final tag = r.isHedge ? 'H' : (r.optType ?? '');
          final tagColor = r.optType == 'CE' ? Colors.indigo : Colors.deepOrange;
          return DataRow(cells: [
            DataCell(_Tag(tag: tag, color: tagColor)),
            DataCell(Text(r.strike?.toStringAsFixed(0) ?? '--')),
            DataCell(Text('${r.lots.toInt()}')),
            DataCell(Text(r.entryPrice?.toStringAsFixed(1) ?? '--')),
            DataCell(Text(r.exitPrice?.toStringAsFixed(1) ?? '--')),
            DataCell(PnlText(pnl,
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12))),
            DataCell(_ReasonNote(text: r.exitReason)),
          ]);
        }).toList(),
      ),
    );
  }
}

// ─── Small shared widgets ────────────────────────────────────────────────────

class _IndexPriceRow extends StatelessWidget {
  final List<IndexPrice> indices;
  const _IndexPriceRow({required this.indices});

  @override
  Widget build(BuildContext context) {
    final indexMap = {for (final i in indices) i.name: i};
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Row(
        children: _indexOrder.map((name) {
          final price = indexMap[name];
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text('$name  ',
                      style: Theme.of(context)
                          .textTheme
                          .labelMedium
                          ?.copyWith(color: cs.primary)),
                  Text(
                    price != null ? price.spot.toStringAsFixed(2) : '--',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _BucketChip extends StatelessWidget {
  final String bucket;
  const _BucketChip({required this.bucket});

  @override
  Widget build(BuildContext context) {
    final color = _bucketColor(bucket);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(bucket,
          style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600)),
    );
  }
}

class _Tag extends StatelessWidget {
  final String tag;
  final Color color;
  const _Tag({required this.tag, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(tag,
          style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11)),
    );
  }
}

class _ReasonNote extends StatelessWidget {
  final String? text;
  const _ReasonNote({required this.text});

  @override
  Widget build(BuildContext context) {
    final t = (text == null || text!.isEmpty) ? '--' : text!;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 160),
      child: Tooltip(
        message: t,
        child: Text(t,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 11)),
      ),
    );
  }
}

class _GroupLabel extends StatelessWidget {
  final String text;
  const _GroupLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Text(text,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
    );
  }
}

class _MutedLine extends StatelessWidget {
  final String text;
  const _MutedLine(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 2),
      child: Text(text, style: const TextStyle(fontSize: 12, color: Colors.grey)),
    );
  }
}

class _EmptyCard extends StatelessWidget {
  final String message;
  const _EmptyCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Center(
            child: Text(message, style: Theme.of(context).textTheme.bodySmall)),
      ),
    );
  }
}

Color _bucketColor(String bucket) {
  switch (bucket.toLowerCase()) {
    case 'complete_bull':
    case 'most_bull':
      return Colors.green;
    case 'more_bull':
      return Colors.lightGreen;
    case 'complete_bear':
    case 'most_bear':
      return Colors.red;
    case 'more_bear':
      return Colors.orange;
    case 'neutral':
      return Colors.blueGrey;
    default:
      return Colors.grey;
  }
}
