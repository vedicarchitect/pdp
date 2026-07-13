/// Daily P&L tab — entry→exit economics for a given IST trading date.
///
/// Shows:
///   • Summary hero cards: total realized / unrealized / net P&L / open legs
///   • Per-index realized P&L breakdown strip
///   • Closed trades table with symbol / lots / entry / exit / P&L columns
///   • Open (unclosed) legs section
///   • Date selector (defaults to today; can go back up to 30 calendar days)
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/manage_providers.dart';
import '../../domain/execution_models.dart';

// ─── Providers ─────────────────────────────────────────────────────────────────

/// Currently-selected IST date string for the daily P&L tab.
final _dailyDateProvider = StateProvider.autoDispose<DateTime>((ref) => DateTime.now());

// ─── Root widget ───────────────────────────────────────────────────────────────

class DailyPnlTab extends ConsumerWidget {
  const DailyPnlTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedDate = ref.watch(_dailyDateProvider);
    final dateStr = DateFormat('yyyy-MM-dd').format(selectedDate);

    final pnlAsync = ref.watch(stranglePnlProvider);
    final tradesAsync = ref.watch(strangleTradesProvider(dateStr));

    return Column(
      children: [
        _DateSelectorBar(selectedDate: selectedDate, ref: ref),
        Expanded(
          child: tradesAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, _) => _ErrorView(
              error: err,
              onRetry: () => ref.invalidate(strangleTradesProvider(dateStr)),
            ),
            data: (trades) => RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(strangleTradesProvider(dateStr));
                ref.invalidate(stranglePnlProvider);
              },
              child: _DailyBody(
                dateStr: dateStr,
                trades: trades,
                pnlAsync: pnlAsync,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ─── Date selector bar ─────────────────────────────────────────────────────────

class _DateSelectorBar extends StatelessWidget {
  final DateTime selectedDate;
  final WidgetRef ref;

  const _DateSelectorBar({required this.selectedDate, required this.ref});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final today = DateTime.now();
    final isToday = _isSameDay(selectedDate, today);
    return Container(
      color: AppColors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.chevron_left, size: 20),
            tooltip: 'Previous day',
            onPressed: _canGoBack(selectedDate)
                ? () => ref.read(_dailyDateProvider.notifier).state =
                    selectedDate.subtract(const Duration(days: 1))
                : null,
          ),
          Expanded(
            child: GestureDetector(
              onTap: () async {
                final picked = await showDatePicker(
                  context: context,
                  initialDate: selectedDate,
                  firstDate: today.subtract(const Duration(days: 30)),
                  lastDate: today,
                );
                if (picked != null) {
                  ref.read(_dailyDateProvider.notifier).state = picked;
                }
              },
              child: Center(
                child: Text(
                  isToday
                      ? 'Today (${DateFormat('dd MMM').format(selectedDate)})'
                      : DateFormat('EEE, dd MMM yyyy').format(selectedDate),
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(color: cs.primary, fontWeight: FontWeight.w600),
                ),
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.chevron_right, size: 20),
            tooltip: 'Next day',
            onPressed: !isToday
                ? () => ref.read(_dailyDateProvider.notifier).state =
                    selectedDate.add(const Duration(days: 1))
                : null,
          ),
          IconButton(
            icon: const Icon(Icons.calendar_today, size: 18),
            tooltip: 'Today',
            onPressed: isToday
                ? null
                : () => ref.read(_dailyDateProvider.notifier).state = today,
          ),
        ],
      ),
    );
  }

  bool _isSameDay(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;

  bool _canGoBack(DateTime d) {
    final limit = DateTime.now().subtract(const Duration(days: 30));
    return d.isAfter(limit);
  }
}

// ─── Main body ─────────────────────────────────────────────────────────────────

class _DailyBody extends StatelessWidget {
  final String dateStr;
  final StrangleTrades trades;
  final AsyncValue<StranglePnl> pnlAsync;

  const _DailyBody({
    required this.dateStr,
    required this.trades,
    required this.pnlAsync,
  });

  @override
  Widget build(BuildContext context) {
    final allRows = trades.byIndex.values.expand((l) => l).toList();
    final closedRows = allRows.where((r) => !r.open).toList();
    final openRows = allRows.where((r) => r.open).toList();
    final totalPnl = closedRows.fold<double>(0, (s, r) => s + (r.pnl ?? 0));

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        pnlAsync.when(
          data: (pnl) => _SummaryCards(pnl: pnl),
          loading: () => const _SummaryCardsSkeleton(),
          error: (_, __) => const SizedBox.shrink(),
        ),
        const SizedBox(height: 8),
        if (trades.byIndex.isNotEmpty) ...[
          _SectionHeader(
              title: 'By Index', trailing: _pnlLabel(totalPnl, context)),
          _IndexPnlStrip(byIndex: trades.byIndex),
          const SizedBox(height: 8),
        ],
        _SectionHeader(
          title: 'Closed Trades (${closedRows.length})',
          trailing: Text(
            '${closedRows.length} round-trips',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        if (closedRows.isEmpty)
          _EmptyCard(
            icon: Icons.receipt_long,
            message: 'No closed trades for $dateStr',
          )
        else
          _TradesTable(rows: closedRows),
        const SizedBox(height: 12),
        _SectionHeader(
          title: 'Open Legs (${openRows.length})',
          trailing: openRows.isNotEmpty
              ? Chip(
                  label: const Text('ACTIVE'),
                  backgroundColor: Colors.orange.withValues(alpha: 0.15),
                  labelStyle: const TextStyle(
                      color: Colors.orange,
                      fontSize: 10,
                      fontWeight: FontWeight.bold),
                  padding: EdgeInsets.zero,
                )
              : null,
        ),
        if (openRows.isEmpty)
          const _EmptyCard(
            icon: Icons.check_circle_outline,
            message: 'No open legs — all squared off',
          )
        else
          _OpenLegsCard(rows: openRows),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _pnlLabel(double pnl, BuildContext context) {
    return PnlText(pnl, style: Theme.of(context).textTheme.labelMedium);
  }
}

// ─── Summary hero cards ────────────────────────────────────────────────────────

class _SummaryCards extends StatelessWidget {
  final StranglePnl pnl;
  const _SummaryCards({required this.pnl});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            _HeroCard(
              label: 'Net P&L',
              value: pnl.totalPnl,
              icon: Icons.show_chart,
              primary: true,
            ),
            _HeroCard(
              label: 'Realized',
              value: pnl.totalRealized,
              icon: Icons.lock_outline,
            ),
          ],
        ),
        Row(
          children: [
            _HeroCard(
              label: 'Unrealized',
              value: pnl.totalUnrealized,
              icon: Icons.pending_outlined,
            ),
            _HeroCard(
              label: 'Open Legs',
              value: pnl.totalOpenLegs.toDouble(),
              icon: Icons.layers,
              isCurrency: false,
            ),
          ],
        ),
      ],
    );
  }
}

class _HeroCard extends StatelessWidget {
  final String label;
  final double value;
  final IconData icon;
  final bool primary;
  final bool isCurrency;

  const _HeroCard({
    required this.label,
    required this.value,
    required this.icon,
    this.primary = false,
    this.isCurrency = true,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final positive = value >= 0;
    final color = isCurrency
        ? (positive ? AppColors.profit : AppColors.loss)
        : cs.primary;

    return Expanded(
      child: Card(
        margin: const EdgeInsets.all(3),
        color: primary ? cs.primaryContainer : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(icon, size: 14, color: color),
                  const SizedBox(width: 4),
                  Text(label,
                      style: Theme.of(context)
                          .textTheme
                          .labelSmall
                          ?.copyWith(color: cs.onSurfaceVariant)),
                ],
              ),
              const SizedBox(height: 4),
              isCurrency
                  ? PnlText(
                      value,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold, color: color),
                    )
                  : Text(
                      value.toInt().toString(),
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.bold, color: color),
                    ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SummaryCardsSkeleton extends StatelessWidget {
  const _SummaryCardsSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(children: [
          Expanded(child: _SkeletonCard()),
          Expanded(child: _SkeletonCard()),
        ]),
        Row(children: [
          Expanded(child: _SkeletonCard()),
          Expanded(child: _SkeletonCard()),
        ]),
      ],
    );
  }
}

class _SkeletonCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.all(3),
      child: Container(height: 64, color: AppColors.surface),
    );
  }
}

// ─── Per-index P&L strip ──────────────────────────────────────────────────────

class _IndexPnlStrip extends StatelessWidget {
  final Map<String, List<StrangleTradeRow>> byIndex;

  const _IndexPnlStrip({required this.byIndex});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: byIndex.entries.map((entry) {
            final indexPnl = entry.value
                .where((r) => !r.open)
                .fold<double>(0, (s, r) => s + (r.pnl ?? 0));
            return Expanded(
              child: Column(
                children: [
                  Text(entry.key,
                      style: Theme.of(context).textTheme.labelSmall),
                  const SizedBox(height: 2),
                  PnlText(
                    indexPnl,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}

// ─── Trades table ─────────────────────────────────────────────────────────────

class _TradesTable extends StatelessWidget {
  final List<StrangleTradeRow> rows;
  const _TradesTable({required this.rows});

  static final _nf = NumberFormat('#,##0.00');
  static final _timeFmt = DateFormat('HH:mm:ss');

  String _fmtTime(String? iso) {
    if (iso == null) return '--';
    try {
      return _timeFmt.format(DateTime.parse(iso).toLocal());
    } catch (_) {
      return iso;
    }
  }

  String _fmtPrice(double? v) => v != null ? _nf.format(v) : '--';

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(
      child: Column(
        children: [
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                Expanded(flex: 3, child: _ColHeader('Symbol')),
                Expanded(flex: 1, child: _ColHeader('Lots')),
                Expanded(flex: 2, child: _ColHeader('Entry')),
                Expanded(flex: 2, child: _ColHeader('Exit')),
                Expanded(flex: 2, child: _ColHeader('P&L', right: true)),
              ],
            ),
          ),
          const Divider(height: 1),
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: rows.length,
            separatorBuilder: (_, __) =>
                const Divider(height: 1, indent: 12, endIndent: 12),
            itemBuilder: (context, i) {
              final r = rows[i];
              final pnl = r.pnl ?? 0;
              final pnlColor = pnl >= 0 ? AppColors.profit : AppColors.loss;
              return Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Row(
                  children: [
                    Expanded(
                      flex: 3,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            r.symbol ?? '${r.optType ?? ''} ${r.strike?.toInt() ?? ''}',
                            style: Theme.of(context)
                                .textTheme
                                .bodySmall
                                ?.copyWith(fontWeight: FontWeight.w500),
                            overflow: TextOverflow.ellipsis,
                          ),
                          if (r.isHedge)
                            Text('HEDGE',
                                style: Theme.of(context)
                                    .textTheme
                                    .labelSmall
                                    ?.copyWith(
                                        color: cs.tertiary, fontSize: 9)),
                        ],
                      ),
                    ),
                    Expanded(
                        flex: 1,
                        child: Text('${r.lots.toInt()}',
                            style: Theme.of(context).textTheme.bodySmall)),
                    Expanded(
                      flex: 2,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(_fmtPrice(r.entryPrice),
                              style: Theme.of(context).textTheme.bodySmall),
                          Text(_fmtTime(r.entryTime),
                              style: Theme.of(context)
                                  .textTheme
                                  .labelSmall
                                  ?.copyWith(color: cs.onSurfaceVariant)),
                        ],
                      ),
                    ),
                    Expanded(
                      flex: 2,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(_fmtPrice(r.exitPrice),
                              style: Theme.of(context).textTheme.bodySmall),
                          Text(_fmtTime(r.exitTime),
                              style: Theme.of(context)
                                  .textTheme
                                  .labelSmall
                                  ?.copyWith(color: cs.onSurfaceVariant)),
                        ],
                      ),
                    ),
                    Expanded(
                      flex: 2,
                      child: Align(
                        alignment: Alignment.centerRight,
                        child: Text(
                          'Rs.${_nf.format(pnl)}',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: pnlColor, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _ColHeader extends StatelessWidget {
  final String text;
  final bool right;
  const _ColHeader(this.text, {this.right = false});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: right ? Alignment.centerRight : Alignment.centerLeft,
      child: Text(
        text,
        style: Theme.of(context)
            .textTheme
            .labelSmall
            ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
      ),
    );
  }
}

// ─── Open legs card ───────────────────────────────────────────────────────────

class _OpenLegsCard extends StatelessWidget {
  final List<StrangleTradeRow> rows;
  const _OpenLegsCard({required this.rows});

  static final _nf = NumberFormat('#,##0.00');

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        itemCount: rows.length,
        separatorBuilder: (_, __) =>
            const Divider(height: 1, indent: 12, endIndent: 12),
        itemBuilder: (context, i) {
          final r = rows[i];
          return ListTile(
            dense: true,
            leading: CircleAvatar(
              radius: 14,
              backgroundColor: cs.primaryContainer,
              child: Text(
                r.optType ?? '?',
                style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    color: cs.primary),
              ),
            ),
            title: Text(
              r.symbol ?? '${r.optType ?? ''} ${r.strike?.toInt() ?? ''}',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(fontWeight: FontWeight.w500),
            ),
            subtitle: Text(
              'Entry Rs.${_nf.format(r.entryPrice ?? 0)}  x  ${r.lots.toInt()} lots${r.isHedge ? '  HEDGE' : ''}',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: cs.onSurfaceVariant),
            ),
            trailing: Chip(
              label: const Text('OPEN'),
              backgroundColor: Colors.amber.withValues(alpha: 0.15),
              labelStyle: const TextStyle(
                  color: Colors.amber,
                  fontSize: 10,
                  fontWeight: FontWeight.bold),
              padding: EdgeInsets.zero,
              visualDensity: VisualDensity.compact,
            ),
          );
        },
      ),
    );
  }
}

// ─── Section header ───────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String title;
  final Widget? trailing;
  const _SectionHeader({required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Text(title,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                  fontWeight: FontWeight.w600)),
          const Spacer(),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

// ─── Empty card ───────────────────────────────────────────────────────────────

class _EmptyCard extends StatelessWidget {
  final IconData icon;
  final String message;
  const _EmptyCard({required this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon,
                  size: 32,
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
              const SizedBox(height: 8),
              Text(message,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── Error view ───────────────────────────────────────────────────────────────

class _ErrorView extends StatelessWidget {
  final Object error;
  final VoidCallback onRetry;
  const _ErrorView({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, size: 40, color: Colors.orange),
          const SizedBox(height: 12),
          Text('Failed to load trades',
              style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 4),
          Text(
            error.toString(),
            textAlign: TextAlign.center,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }
}
