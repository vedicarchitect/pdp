import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../shared/widgets/pnl_text.dart';
import '../application/holdings_providers.dart';
import '../domain/holdings_models.dart';

/// F&O Intraday positions (synced from Dhan via broker_sync).
/// This tab is strictly read-only and reflects the manual account state.
class PositionsTab extends ConsumerWidget {
  const PositionsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final positionsAsync = ref.watch(livePositionsProvider);

    return positionsAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err')),
      data: (positions) {
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Positions (${positions.length})', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            if (positions.isEmpty)
              const _EmptyPositions()
            else
              ListView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: positions.length,
                itemBuilder: (context, i) => _PositionRow(position: positions[i]),
              ),
          ],
        );
      },
    );
  }
}

class _PositionRow extends StatelessWidget {
  const _PositionRow({required this.position});

  final PositionDetail position;

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
                      position.symbol,
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
                        position.productType,
                        style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  'Net Qty: ${position.netQty} · Avg: ₹${position.netQty >= 0 ? position.buyAvg.toStringAsFixed(2) : position.sellAvg.toStringAsFixed(2)}${position.ltp > 0 ? ' · LTP: ₹${position.ltp.toStringAsFixed(2)}' : ''}',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text('Unrealized', style: TextStyle(fontSize: 10, color: AppColors.textMuted)),
              PnlText(
                position.liveUnrealizedPnl,
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              const Text('Realized', style: TextStyle(fontSize: 10, color: AppColors.textMuted)),
              PnlText(
                position.realizedPnl,
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w500),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _EmptyPositions extends StatelessWidget {
  const _EmptyPositions();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Column(
          children: [
            Icon(Icons.inbox_outlined, size: 36, color: AppColors.textMuted),
            SizedBox(height: 10),
            Text('No open positions found', style: TextStyle(color: AppColors.textMuted)),
          ],
        ),
      ),
    );
  }
}
