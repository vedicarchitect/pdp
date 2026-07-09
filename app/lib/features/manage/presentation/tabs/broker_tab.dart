/// Broker (Dhan) tab — the broker's own account view (holdings / positions /
/// funds) from `/api/v1/broker-sync/*`. Same grouped layout as the Positions
/// tab but WITHOUT entry/exit reasons (these are manual broker rows, not
/// system-placed). A staleness badge reflects the last intraday sync.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/manage_providers.dart';
import '../../domain/broker_models.dart';

class BrokerTab extends ConsumerWidget {
  const BrokerTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accountAsync = ref.watch(brokerAccountProvider);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(brokerAccountProvider),
      child: accountAsync.when(
        data: (acct) => _BrokerBody(acct: acct),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => ListView(
          children: [
            const SizedBox(height: 80),
            const Icon(Icons.cloud_off, size: 48, color: Colors.orange),
            const SizedBox(height: 12),
            Center(child: Text('Broker account unavailable',
                style: Theme.of(context).textTheme.titleMedium)),
            const SizedBox(height: 4),
            Center(
              child: Text('$err',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall),
            ),
          ],
        ),
      ),
    );
  }
}

class _BrokerBody extends StatelessWidget {
  final BrokerAccount acct;
  const _BrokerBody({required this.acct});

  @override
  Widget build(BuildContext context) {
    final openPositions = acct.positions.where((p) => p.isOpen).toList();
    final closedPositions = acct.positions.where((p) => !p.isOpen).toList();

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        _SyncBadge(lastSyncedAt: acct.lastSyncedAt),
        const SizedBox(height: 8),
        if (acct.fund != null) _FundCard(fund: acct.fund!),
        const SizedBox(height: 8),
        _SectionHeader('Positions — Open (${openPositions.length})'),
        if (openPositions.isEmpty)
          const _MutedLine('no open broker positions')
        else
          _PositionsTable(rows: openPositions),
        const SizedBox(height: 8),
        _SectionHeader('Positions — Closed (${closedPositions.length})'),
        if (closedPositions.isEmpty)
          const _MutedLine('no closed broker positions')
        else
          _PositionsTable(rows: closedPositions),
        const SizedBox(height: 12),
        _SectionHeader('Holdings (${acct.holdings.length})'),
        if (acct.holdings.isEmpty)
          const _MutedLine('no holdings')
        else
          _HoldingsTable(rows: acct.holdings),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _SyncBadge extends StatelessWidget {
  final String? lastSyncedAt;
  const _SyncBadge({required this.lastSyncedAt});

  @override
  Widget build(BuildContext context) {
    DateTime? ts;
    if (lastSyncedAt != null) {
      ts = DateTime.tryParse(lastSyncedAt!)?.toLocal();
    }
    final now = DateTime.now();
    final ageMin = ts != null ? now.difference(ts).inMinutes : null;
    // Intraday poller default is 5 min; flag stale beyond ~15 min.
    final stale = ageMin == null || ageMin > 15;
    final color = stale ? Colors.orange : AppColors.profit;
    final label = ts == null
        ? 'Never synced — start broker sync or check Dhan credentials'
        : 'Synced ${_ago(ageMin!)} (${_hhmm(ts)})';

    return Row(
      children: [
        Icon(stale ? Icons.sync_problem : Icons.sync, size: 16, color: color),
        const SizedBox(width: 6),
        Text(label, style: TextStyle(color: color, fontSize: 12)),
      ],
    );
  }

  String _ago(int min) {
    if (min < 1) return 'just now';
    if (min < 60) return '${min}m ago';
    return '${(min / 60).floor()}h ago';
  }

  String _hhmm(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

class _FundCard extends StatelessWidget {
  final BrokerFund fund;
  const _FundCard({required this.fund});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            _fundCol(context, 'Available', fund.availableBalance),
            _fundCol(context, 'Utilized', fund.utilizedAmount),
            _fundCol(context, 'Collateral', fund.collateralAmount),
            _fundCol(context, 'Withdrawable', fund.withdrawableBalance),
          ],
        ),
      ),
    );
  }

  Widget _fundCol(BuildContext context, String label, double value) {
    return Expanded(
      child: Column(
        children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          const SizedBox(height: 2),
          Text('₹${value.toStringAsFixed(0)}',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
        ],
      ),
    );
  }
}

class _PositionsTable extends StatelessWidget {
  final List<BrokerPosition> rows;
  const _PositionsTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 44,
        columnSpacing: 14,
        columns: const [
          DataColumn(label: Text('Symbol')),
          DataColumn(label: Text('Segment')),
          DataColumn(label: Text('Net Qty'), numeric: true),
          DataColumn(label: Text('Buy Avg'), numeric: true),
          DataColumn(label: Text('Sell Avg'), numeric: true),
          DataColumn(label: Text('Realized'), numeric: true),
          DataColumn(label: Text('Unrealized'), numeric: true),
        ],
        rows: rows.map((p) {
          return DataRow(cells: [
            DataCell(Text(p.symbol ?? p.securityId,
                style: const TextStyle(fontWeight: FontWeight.w500))),
            DataCell(Text(p.exchangeSegment, style: const TextStyle(fontSize: 11))),
            DataCell(Text('${p.netQty}')),
            DataCell(Text(p.buyAvg.toStringAsFixed(1))),
            DataCell(Text(p.sellAvg.toStringAsFixed(1))),
            DataCell(PnlText(p.realizedPnl,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
            DataCell(PnlText(p.unrealizedPnl,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
          ]);
        }).toList(),
      ),
    );
  }
}

class _HoldingsTable extends StatelessWidget {
  final List<BrokerHolding> rows;
  const _HoldingsTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 44,
        columnSpacing: 14,
        columns: const [
          DataColumn(label: Text('Symbol')),
          DataColumn(label: Text('Exch')),
          DataColumn(label: Text('Qty'), numeric: true),
          DataColumn(label: Text('Avg Cost'), numeric: true),
          DataColumn(label: Text('LTP'), numeric: true),
          DataColumn(label: Text('P&L'), numeric: true),
        ],
        rows: rows.map((h) {
          return DataRow(cells: [
            DataCell(Text(h.symbol ?? h.securityId,
                style: const TextStyle(fontWeight: FontWeight.w500))),
            DataCell(Text(h.exchange ?? '', style: const TextStyle(fontSize: 11))),
            DataCell(Text('${h.totalQty}')),
            DataCell(Text(h.avgCostPrice.toStringAsFixed(1))),
            DataCell(Text(h.lastPrice != null ? h.lastPrice!.toStringAsFixed(1) : '--')),
            DataCell(PnlText(h.pnl,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
          ]);
        }).toList(),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String text;
  const _SectionHeader(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Text(text,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: Theme.of(context).colorScheme.primary,
              fontWeight: FontWeight.w600)),
    );
  }
}

class _MutedLine extends StatelessWidget {
  final String text;
  const _MutedLine(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, top: 2, bottom: 2),
      child: Text(text, style: const TextStyle(fontSize: 12, color: Colors.grey)),
    );
  }
}
