/// Indicator matrix panel — the EMA/ST/PSAR/RSI/VWAP × timeframe grid plus
/// Camarilla + period levels, per index. Extracted from the execution tab so it
/// can live in a dedicated side panel (desktop) or stacked pane (narrow), off
/// the positions scroll.
library;

import 'package:flutter/material.dart';

import '../domain/execution_models.dart';

// Timeframes shown in the indicator matrix
const _matrixTfs = ['5m', '15m', '30m', '1H', '1D'];

// Index name → security_id and canonical order
const _indexSids = {'NIFTY': '13', 'BANKNIFTY': '25', 'SENSEX': '51'};
const _indexOrder = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

/// Public entry point: renders the full indicator matrix for all sids, plus the
/// NIFTY ATM CE/PE rows when present.
class IndicatorPanel extends StatelessWidget {
  final Map<String, SidIndicators> indicators;
  final AtmOptionRow? atmCe;
  final AtmOptionRow? atmPe;

  const IndicatorPanel({
    super.key,
    required this.indicators,
    this.atmCe,
    this.atmPe,
  });

  @override
  Widget build(BuildContext context) {
    final sidOrder = _indexOrder.map((n) => _indexSids[n]!).toList();
    final sids = [
      ...sidOrder.where(indicators.containsKey),
      ...indicators.keys.where((k) => !sidOrder.contains(k)),
    ];

    if (sids.isEmpty && atmCe == null && atmPe == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Center(
            child: Text('No indicator data',
                style: Theme.of(context).textTheme.bodySmall),
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 4, top: 4),
          child: Text('Indicator Matrix',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: Theme.of(context).colorScheme.primary)),
        ),
        ...sids.map((sid) {
          final ind = indicators[sid]!;
          final name = _indexSids.entries
              .firstWhere((e) => e.value == sid, orElse: () => MapEntry(sid, sid))
              .key;
          return _SidMatrix(name: name, ind: ind);
        }),
        if (atmCe != null) _AtmOptionMatrix(row: atmCe!),
        if (atmPe != null) _AtmOptionMatrix(row: atmPe!),
      ],
    );
  }
}

class _SidMatrix extends StatefulWidget {
  final String name;
  final SidIndicators ind;

  const _SidMatrix({required this.name, required this.ind});

  @override
  State<_SidMatrix> createState() => _SidMatrixState();
}

class _SidMatrixState extends State<_SidMatrix> {
  // Own a controller so the horizontal Scrollbar shows a persistent thumb — the
  // 15-column matrix is wider than its fixed-width panel, and without a visible
  // affordance the rightmost columns (CamR4/CamS4) look clipped off-screen.
  final _hScroll = ScrollController();

  @override
  void dispose() {
    _hScroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.name;
    final ind = widget.ind;
    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(name,
                    style: Theme.of(context)
                        .textTheme
                        .labelMedium
                        ?.copyWith(fontWeight: FontWeight.bold)),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Cam: 5-15m daily · 30m/1H weekly · 1D monthly',
                    style: TextStyle(fontSize: 9, color: Colors.grey),
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Scrollbar(
              controller: _hScroll,
              thumbVisibility: true,
              child: SingleChildScrollView(
                controller: _hScroll,
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.only(bottom: 6),
                child: DataTable(
                  headingRowHeight: 28,
                  dataRowMinHeight: 32,
                  dataRowMaxHeight: 32,
                  columnSpacing: 8,
                  columns: const [
                    DataColumn(label: Text('TF')),
                    DataColumn(label: Text('ST(10,2)'), numeric: true),
                    DataColumn(label: Text('ST(10,3)'), numeric: true),
                    DataColumn(label: Text('ST(3,1)'), numeric: true),
                    DataColumn(label: Text('EMA9'), numeric: true),
                    DataColumn(label: Text('EMA20'), numeric: true),
                    DataColumn(label: Text('EMA50'), numeric: true),
                    DataColumn(label: Text('EMA100'), numeric: true),
                    DataColumn(label: Text('EMA200'), numeric: true),
                    DataColumn(label: Text('PSAR'), numeric: true),
                    DataColumn(label: Text('RSI'), numeric: true),
                    DataColumn(label: Text('VWAP'), numeric: true),
                    DataColumn(label: Text('VWMA'), numeric: true),
                    DataColumn(label: Text('CamR4'), numeric: true),
                    DataColumn(label: Text('CamS4'), numeric: true),
                  ],
                  rows: _matrixTfs
                      .map((tf) => _tfRow(context, tf, ind.tf[tf], ind.camForTf(tf)))
                      .toList(),
                ),
              ),
            ),
            if (ind.pdh != null || ind.pwh != null || ind.pmh != null) ...[
              const SizedBox(height: 4),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  if (ind.pdh != null)
                    _LevelPill(label: 'PDH', value: ind.pdh, color: Colors.blue),
                  if (ind.pdl != null)
                    _LevelPill(label: 'PDL', value: ind.pdl, color: Colors.blueGrey),
                  if (ind.pwh != null)
                    _LevelPill(label: 'PWH', value: ind.pwh, color: Colors.purple),
                  if (ind.pwl != null)
                    _LevelPill(label: 'PWL', value: ind.pwl, color: Colors.deepPurple),
                  if (ind.pmh != null)
                    _LevelPill(label: 'PMH', value: ind.pmh, color: Colors.teal),
                  if (ind.pml != null)
                    _LevelPill(label: 'PML', value: ind.pml, color: Colors.tealAccent),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  DataRow _tfRow(
      BuildContext context, String tf, IndicatorCell? cell, CamarillaLevels? cam) {
    Color? rsiColor;
    if (cell?.rsi != null && cell?.rsiMa != null) {
      rsiColor = cell!.rsi! >= cell.rsiMa! ? Colors.green : Colors.red;
    }
    final rsiText = cell?.rsi != null
        ? '${cell!.rsi!.toStringAsFixed(0)}/${_fmtOpt(cell.rsiMa)}'
        : '--';

    return DataRow(cells: [
      DataCell(Text(tf,
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11))),
      _stCell(cell?.st1020),
      _stCell(cell?.st1030),
      _stCell(cell?.st31),
      DataCell(Text(_fmtOpt(cell?.ema9))),
      DataCell(Text(_fmtOpt(cell?.ema20))),
      DataCell(Text(_fmtOpt(cell?.ema50))),
      DataCell(Text(_fmtOpt(cell?.ema100))),
      DataCell(Text(_fmtOpt(cell?.ema200))),
      DataCell(Text(_fmtOpt(cell?.psar))),
      DataCell(Text(rsiText, style: TextStyle(color: rsiColor, fontSize: 11))),
      DataCell(Text(_fmtOpt(cell?.vwap))),
      DataCell(Text(_fmtOpt(cell?.vwma))),
      DataCell(Text(_fmtOpt(cam?.r4),
          style: const TextStyle(color: Colors.redAccent, fontSize: 11))),
      DataCell(Text(_fmtOpt(cam?.s4),
          style: const TextStyle(color: Colors.greenAccent, fontSize: 11))),
    ]);
  }
}

/// Renders one SuperTrend variant as a direction arrow — shared by the index
/// matrix and the ATM option matrix.
DataCell _stCell(SuperTrendVariant? v) {
  final dir = v?.direction;
  final icon = dir == 'up'
      ? '▲'
      : dir == 'down'
          ? '▼'
          : '--';
  final color = dir == 'up'
      ? Colors.green
      : dir == 'down'
          ? Colors.red
          : null;
  return DataCell(Text(icon, style: TextStyle(color: color, fontSize: 11)));
}

String _fmtOpt(double? v) => v != null ? v.toStringAsFixed(0) : '--';

/// NIFTY ATM CE/PE matrix row — same column shape as the index matrix minus
/// Camarilla/period levels (index-only concepts, never present on these rows).
class _AtmOptionMatrix extends StatelessWidget {
  final AtmOptionRow row;

  const _AtmOptionMatrix({required this.row});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(row.label,
                style: Theme.of(context)
                    .textTheme
                    .labelMedium
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingRowHeight: 28,
                dataRowMinHeight: 32,
                dataRowMaxHeight: 32,
                columnSpacing: 8,
                columns: const [
                  DataColumn(label: Text('TF')),
                  DataColumn(label: Text('ST(10,2)'), numeric: true),
                  DataColumn(label: Text('ST(10,3)'), numeric: true),
                  DataColumn(label: Text('ST(3,1)'), numeric: true),
                  DataColumn(label: Text('EMA9'), numeric: true),
                  DataColumn(label: Text('EMA20'), numeric: true),
                  DataColumn(label: Text('EMA50'), numeric: true),
                  DataColumn(label: Text('RSI'), numeric: true),
                  DataColumn(label: Text('VWAP'), numeric: true),
                  DataColumn(label: Text('VWMA'), numeric: true),
                ],
                rows: _matrixTfs.map((tf) => _row(tf, row.tf[tf])).toList(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  DataRow _row(String tf, IndicatorCell? cell) {
    Color? rsiColor;
    if (cell?.rsi != null && cell?.rsiMa != null) {
      rsiColor = cell!.rsi! >= cell.rsiMa! ? Colors.green : Colors.red;
    }
    final rsiText = cell?.rsi != null ? cell!.rsi!.toStringAsFixed(0) : '--';

    return DataRow(cells: [
      DataCell(Text(tf, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11))),
      _stCell(cell?.st1020),
      _stCell(cell?.st1030),
      _stCell(cell?.st31),
      DataCell(Text(_fmtOpt(cell?.ema9))),
      DataCell(Text(_fmtOpt(cell?.ema20))),
      DataCell(Text(_fmtOpt(cell?.ema50))),
      DataCell(Text(rsiText, style: TextStyle(color: rsiColor, fontSize: 11))),
      DataCell(Text(_fmtOpt(cell?.vwap))),
      DataCell(Text(_fmtOpt(cell?.vwma))),
    ]);
  }
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
