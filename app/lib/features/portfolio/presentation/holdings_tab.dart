import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../shared/widgets/pnl_text.dart';
import '../../../shared/widgets/stat_card.dart';
import '../application/holdings_providers.dart';
import '../domain/holdings_models.dart';

/// Real equity/ETF holdings (synced from Dhan via broker_sync), with
/// per-stock detail and portfolio-level insight cards.
class HoldingsTab extends ConsumerWidget {
  const HoldingsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final holdingsAsync = ref.watch(holdingsProvider);

    return holdingsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err')),
      data: (data) {
        final summary = data['summary'] as HoldingsSummary;
        final holdings = data['holdings'] as List<HoldingDetail>;
        final isMock = data['is_mock'] as bool? ?? false;

        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (isMock) const _DemoBanner(),
            _SummaryCards(summary: summary),
            const SizedBox(height: 20),
            Text('Holdings (${holdings.length})', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            if (holdings.isEmpty)
              const _EmptyHoldings()
            else
              ListView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: holdings.length,
                itemBuilder: (context, i) => _HoldingRow(holding: holdings[i]),
              ),
          ],
        );
      },
    );
  }
}

class _DemoBanner extends StatelessWidget {
  const _DemoBanner();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: AppColors.warning.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppColors.warning.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.info_outline, size: 18, color: AppColors.warning),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Demo data — no broker sync has run yet, showing sample holdings',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryCards extends StatelessWidget {
  const _SummaryCards({required this.summary});

  final HoldingsSummary summary;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: StatCard(
                label: 'Current Value',
                child: Text('₹${summary.totalCurrentValue.toStringAsFixed(0)}'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: StatCard(
                label: 'Total P&L',
                child: PnlText(summary.totalPnl),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: StatCard(
                label: 'Invested',
                child: Text('₹${summary.totalInvested.toStringAsFixed(0)}'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: StatCard(
                label: 'Return',
                child: PnlText(summary.totalPnlPct, showSign: true),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: StatCard(
                label: 'Cash',
                child: Text('₹${summary.cashAvailable.toStringAsFixed(0)}'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _HoldingRow extends StatelessWidget {
  const _HoldingRow({required this.holding});

  final HoldingDetail holding;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      holding.symbol,
                      style: const TextStyle(fontWeight: FontWeight.w700, color: AppColors.textPrimary),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.surfaceAlt,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        holding.sector,
                        style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  '${holding.qty} @ ₹${holding.avgPrice.toStringAsFixed(2)} · LTP ₹${holding.lastPrice.toStringAsFixed(2)}',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('₹${holding.currentValue.toStringAsFixed(0)}',
                  style: const TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              PnlText(
                holding.pnl,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _EmptyHoldings extends StatelessWidget {
  const _EmptyHoldings();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Column(
          children: [
            Icon(Icons.inbox_outlined, size: 36, color: AppColors.textMuted),
            SizedBox(height: 10),
            Text('No holdings found', style: TextStyle(color: AppColors.textMuted)),
          ],
        ),
      ),
    );
  }
}
