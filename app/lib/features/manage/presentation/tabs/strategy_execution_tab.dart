/// Realtime directional-strangle execution monitor tab.
///
/// Layout:
///   ┌──────────────────────────────────────────────────────────┐
///   │  3 × Index price cards  (NIFTY | BANKNIFTY | SENSEX)    │
///   ├──────────────────────────────────────────────────────────┤
///   │  Strategy status bar (bucket / score / P&L / done)       │
///   ├──────────────────────────────────────────────────────────┤
///   │  Open legs table (entry → Greeks → MtM)                  │
///   ├──────────────────────────────────────────────────────────┤
///   │  Indicator matrix (5m/15m/30m/1H/1D) per index SID      │
///   ├──────────────────────────────────────────────────────────┤
///   │  Recent events log (last 20 closed legs / exits)         │
///   └──────────────────────────────────────────────────────────┘
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/manage_providers.dart';
import '../../domain/execution_models.dart';

// Timeframes shown in the indicator matrix
const _matrixTfs = ['5m', '15m', '30m', '1H', '1D'];

// Index display order
const _indexOrder = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

// Map of index name → security_id
const _indexSids = {
  'NIFTY': '13',
  'BANKNIFTY': '25',
  'SENSEX': '51',
};

class StrategyExecutionTab extends ConsumerWidget {
  const StrategyExecutionTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final monitorAsync = ref.watch(monitorStreamProvider);

    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(monitorStreamProvider);
      },
      child: monitorAsync.when(
        data: (snap) => _MonitorBody(snap: snap),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _ErrorView(error: err, ref: ref),
      ),
    );
  }
}

// ─── Error view ───────────────────────────────────────────────────────────────

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
          Text(
            'Monitor unavailable',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            'Strategy may not be running',
            style: Theme.of(context).textTheme.bodySmall,
          ),
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

// ─── Main body ────────────────────────────────────────────────────────────────

class _MonitorBody extends StatelessWidget {
  final MonitorSnapshot snap;

  const _MonitorBody({required this.snap});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        _IndexPriceRow(indices: snap.indices),
        const SizedBox(height: 8),
        _StatusBar(snap: snap),
        const SizedBox(height: 8),
        if (snap.legs.isNotEmpty) ...[
          _SectionHeader(title: 'Open Legs (${snap.legs.length})'),
          _LegsTable(legs: snap.legs),
          const SizedBox(height: 8),
        ] else
          const _EmptyCard(message: 'No open legs'),
        const _SectionHeader(title: 'Indicator Matrix'),
        _IndicatorMatrix(indicators: snap.indicators),
        const SizedBox(height: 8),
        if (snap.recentEvents.isNotEmpty) ...[
          const _SectionHeader(title: 'Recent Events'),
          _EventLog(events: snap.recentEvents),
        ],
      ],
    );
  }
}

// ─── Index price cards ────────────────────────────────────────────────────────

class _IndexPriceRow extends StatelessWidget {
  final List<IndexPrice> indices;

  const _IndexPriceRow({required this.indices});

  @override
  Widget build(BuildContext context) {
    final indexMap = {for (final i in indices) i.name: i};
    return Row(
      children: _indexOrder.map((name) {
        final price = indexMap[name];
        return Expanded(
          child: _IndexCard(name: name, price: price),
        );
      }).toList(),
    );
  }
}

class _IndexCard extends StatelessWidget {
  final String name;
  final IndexPrice? price;

  const _IndexCard({required this.name, required this.price});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(
      margin: const EdgeInsets.all(3),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name,
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: cs.primary)),
            const SizedBox(height: 2),
            Text(
              price != null ? _fmt(price!.spot) : '--',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            if (price?.future != null)
              Text(
                'Fut: ${_fmt(price!.future!)}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
      ),
    );
  }

  String _fmt(double v) => v.toStringAsFixed(2);
}

// ─── Status bar ───────────────────────────────────────────────────────────────

class _StatusBar extends StatelessWidget {
  final MonitorSnapshot snap;

  const _StatusBar({required this.snap});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final pnlColor = snap.dayPnl >= 0 ? Colors.green : Colors.red;
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            // Bucket chip
            Chip(
              label: Text(snap.bucket,
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              backgroundColor: _bucketColor(snap.bucket).withValues(alpha: 0.15),
              side: BorderSide(color: _bucketColor(snap.bucket), width: 1.5),
            ),
            const SizedBox(width: 8),
            if (snap.score != null)
              Text('Score: ${snap.score!.toStringAsFixed(2)}',
                  style: Theme.of(context).textTheme.bodySmall),
            const Spacer(),
            // P&L chips
            _PnlChip(
                label: 'P&L',
                value: snap.dayPnl,
                color: pnlColor,
                context: context),
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

  Color _bucketColor(String bucket) {
    switch (bucket.toUpperCase()) {
      case 'COMPLETE_BULL':
      case 'MILD_BULL':
        return Colors.green;
      case 'COMPLETE_BEAR':
      case 'MILD_BEAR':
        return Colors.red;
      default:
        return Colors.orange;
    }
  }
}

class _PnlChip extends StatelessWidget {
  final String label;
  final double value;
  final Color color;
  final BuildContext context;

  const _PnlChip({
    required this.label,
    required this.value,
    required this.color,
    required this.context,
  });

  @override
  Widget build(BuildContext ctx) {
    final sign = value >= 0 ? '+' : '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        '$label: $sign${value.toStringAsFixed(0)}',
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w600,
          fontSize: 12,
        ),
      ),
    );
  }
}

// ─── Legs table ───────────────────────────────────────────────────────────────

class _LegsTable extends StatelessWidget {
  final List<LegRow> legs;

  const _LegsTable({required this.legs});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 32,
        dataRowMinHeight: 36,
        dataRowMaxHeight: 52,
        columnSpacing: 10,
        columns: const [
          DataColumn(label: Text('Type')),
          DataColumn(label: Text('Strike'), numeric: true),
          DataColumn(label: Text('Lots'), numeric: true),
          DataColumn(label: Text('Entry ₹'), numeric: true),
          DataColumn(label: Text('LTP ₹'), numeric: true),
          DataColumn(label: Text('MtM ₹'), numeric: true),
          DataColumn(label: Text('Δ'), numeric: true),
          DataColumn(label: Text('θ'), numeric: true),
          DataColumn(label: Text('OI'), numeric: true),
          DataColumn(label: Text('PCR'), numeric: true),
          DataColumn(label: Text('Entry Reason')),
        ],
        rows: legs.map((leg) => _legRow(context, leg)).toList(),
      ),
    );
  }

  DataRow _legRow(BuildContext context, LegRow leg) {
    final isCall = leg.optType == 'CE';
    final typeColor = isCall ? Colors.indigo : Colors.deepOrange;
    final mtmColor = (leg.mtm ?? 0) >= 0 ? Colors.green : Colors.red;
    final tag = leg.isHedge
        ? 'H'
        : leg.isMomentum
            ? 'M'
            : leg.optType;

    return DataRow(cells: [
      DataCell(_Tag(tag: tag, color: typeColor)),
      DataCell(Text(leg.strike.toStringAsFixed(0))),
      DataCell(Text('${leg.lots}')),
      DataCell(Text(leg.entryPrice.toStringAsFixed(1))),
      DataCell(Text(leg.ltp != null ? leg.ltp!.toStringAsFixed(1) : '--')),
      DataCell(Text(
        leg.mtm != null ? leg.mtm!.toStringAsFixed(0) : '--',
        style: TextStyle(color: mtmColor, fontWeight: FontWeight.w600),
      )),
      DataCell(Text(
        leg.delta != null ? leg.delta!.toStringAsFixed(3) : '--',
      )),
      DataCell(Text(
        leg.theta != null ? leg.theta!.toStringAsFixed(2) : '--',
      )),
      DataCell(Text(
        leg.oi != null ? _compactInt(leg.oi!) : '--',
      )),
      DataCell(Text(
        leg.pcr != null ? leg.pcr!.toStringAsFixed(2) : '--',
      )),
      DataCell(Text(
        leg.entryReason ?? '--',
        style: const TextStyle(fontSize: 11),
      )),
    ]);
  }

  String _compactInt(int v) {
    if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(1)}M';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(0)}K';
    return '$v';
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
      child: Text(
        tag,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.bold,
          fontSize: 11,
        ),
      ),
    );
  }
}

// ─── Indicator matrix ─────────────────────────────────────────────────────────

class _IndicatorMatrix extends StatelessWidget {
  final Map<String, SidIndicators> indicators;

  const _IndicatorMatrix({required this.indicators});

  @override
  Widget build(BuildContext context) {
    final sidOrder = _indexOrder.map((n) => _indexSids[n]!).toList();
    final sids = [
      ...sidOrder.where(indicators.containsKey),
      ...indicators.keys.where((k) => !sidOrder.contains(k)),
    ];

    if (sids.isEmpty) {
      return const _EmptyCard(message: 'No indicator data');
    }

    return Column(
      children: sids.map((sid) {
        final ind = indicators[sid]!;
        final name = _indexSids.entries
            .firstWhere((e) => e.value == sid,
                orElse: () => MapEntry(sid, sid))
            .key;
        return _SidMatrix(name: name, ind: ind);
      }).toList(),
    );
  }
}

class _SidMatrix extends StatelessWidget {
  final String name;
  final SidIndicators ind;

  const _SidMatrix({required this.name, required this.ind});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header row
            Row(
              children: [
                Text(name,
                    style: Theme.of(context)
                        .textTheme
                        .labelMedium
                        ?.copyWith(fontWeight: FontWeight.bold)),
                const Spacer(),
                if (ind.camarillaDaily != null)
                  _LevelPill(
                    label: 'Cam R4',
                    value: ind.camarillaDaily!.r4,
                    color: Colors.red,
                  ),
                const SizedBox(width: 4),
                if (ind.camarillaDaily != null)
                  _LevelPill(
                    label: 'Cam S4',
                    value: ind.camarillaDaily!.s4,
                    color: Colors.green,
                  ),
              ],
            ),
            const SizedBox(height: 6),
            // TF grid
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingRowHeight: 28,
                dataRowMinHeight: 32,
                dataRowMaxHeight: 32,
                columnSpacing: 8,
                columns: const [
                  DataColumn(label: Text('TF')),
                  DataColumn(label: Text('ST'), numeric: true),
                  DataColumn(label: Text('EMA9'), numeric: true),
                  DataColumn(label: Text('EMA20'), numeric: true),
                  DataColumn(label: Text('EMA50'), numeric: true),
                  DataColumn(label: Text('PSAR'), numeric: true),
                ],
                rows: _matrixTfs
                    .map((tf) => _tfRow(context, tf, ind.tf[tf]))
                    .toList(),
              ),
            ),
            // PDH / PDL / PWH / PWL
            if (ind.pdh != null || ind.pwh != null) ...[
              const SizedBox(height: 4),
              Wrap(
                spacing: 8,
                children: [
                  if (ind.pdh != null)
                    _LevelPill(
                        label: 'PDH',
                        value: ind.pdh,
                        color: Colors.blue),
                  if (ind.pdl != null)
                    _LevelPill(
                        label: 'PDL',
                        value: ind.pdl,
                        color: Colors.blueGrey),
                  if (ind.pwh != null)
                    _LevelPill(
                        label: 'PWH',
                        value: ind.pwh,
                        color: Colors.purple),
                  if (ind.pwl != null)
                    _LevelPill(
                        label: 'PWL',
                        value: ind.pwl,
                        color: Colors.deepPurple),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  DataRow _tfRow(BuildContext context, String tf, IndicatorCell? cell) {
    final stDir = cell?.stDir;
    final stIcon = stDir == 'up'
        ? '▲'
        : stDir == 'down'
            ? '▼'
            : '--';
    final stColor = stDir == 'up'
        ? Colors.green
        : stDir == 'down'
            ? Colors.red
            : null;

    return DataRow(cells: [
      DataCell(Text(tf,
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11))),
      DataCell(Text(stIcon, style: TextStyle(color: stColor, fontSize: 11))),
      DataCell(Text(_fmtOpt(cell?.ema9))),
      DataCell(Text(_fmtOpt(cell?.ema20))),
      DataCell(Text(_fmtOpt(cell?.ema50))),
      DataCell(Text(_fmtOpt(cell?.psar))),
    ]);
  }

  String _fmtOpt(double? v) => v != null ? v.toStringAsFixed(0) : '--';
}

class _LevelPill extends StatelessWidget {
  final String label;
  final double? value;
  final Color color;

  const _LevelPill({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    if (value == null) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        '$label ${value!.toStringAsFixed(0)}',
        style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ─── Event log ────────────────────────────────────────────────────────────────

class _EventLog extends StatelessWidget {
  final List<Map<String, dynamic>> events;

  const _EventLog({required this.events});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: events.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, i) {
          final ev = events[i];
          final type = ev['event_type'] as String? ?? ev['type'] as String? ?? '?';
          final ts = ev['ts'] as String? ?? ev['timestamp'] as String? ?? '';
          return ListTile(
            dense: true,
            leading: _eventIcon(type),
            title: Text(type,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
            subtitle: Text(_evSummary(ev), style: const TextStyle(fontSize: 11)),
            trailing: Text(
              ts.length > 19 ? ts.substring(11, 19) : ts,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          );
        },
      ),
    );
  }

  Widget _eventIcon(String type) {
    final lower = type.toLowerCase();
    if (lower.contains('close') || lower.contains('stop')) {
      return const Icon(Icons.remove_circle_outline, color: Colors.red, size: 18);
    }
    if (lower.contains('open')) {
      return const Icon(Icons.add_circle_outline, color: Colors.green, size: 18);
    }
    if (lower.contains('profit')) {
      return const Icon(Icons.emoji_events, color: Colors.amber, size: 18);
    }
    return const Icon(Icons.info_outline, size: 18);
  }

  String _evSummary(Map<String, dynamic> ev) {
    final parts = <String>[];
    if (ev['opt_type'] != null) parts.add(ev['opt_type'] as String);
    if (ev['strike'] != null) parts.add('@ ${ev['strike']}');
    if (ev['lots'] != null) parts.add('${ev['lots']} lots');
    if (ev['exit_reason'] != null) parts.add('(${ev['exit_reason']})');
    if (ev['reason'] != null) parts.add('(${ev['reason']})');
    return parts.isEmpty ? '--' : parts.join(' ');
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String title;

  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4, top: 4),
      child: Text(title,
          style: Theme.of(context)
              .textTheme
              .labelLarge
              ?.copyWith(color: Theme.of(context).colorScheme.primary)),
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
          child: Text(message,
              style: Theme.of(context).textTheme.bodySmall),
        ),
      ),
    );
  }
}
