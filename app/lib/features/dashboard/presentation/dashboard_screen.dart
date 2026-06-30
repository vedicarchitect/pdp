import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/pnl_text.dart';
import '../../../shared/widgets/stat_card.dart';
import '../application/dashboard_providers.dart';
import '../domain/dashboard_models.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stream = ref.watch(dashboardStreamProvider);

    return stream.when(
      data: (data) => _buildDashboard(data),
      error: (e, st) => Center(child: Text('Error: $e', style: const TextStyle(color: AppColors.loss))),
      loading: () => const Center(child: CircularProgressIndicator()),
    );
  }

  Widget _buildDashboard(DashboardData data) {
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: SizedBox(
            height: 130,
            child: ListView.builder(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              itemCount: data.indices.length,
              itemBuilder: (context, i) => _MarketIndexCard(index: data.indices[i]),
            ),
          ),
        ),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Portfolio Snapshot',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: StatCard(
                        label: 'Day P&L',
                        child: PnlText(data.summary.dayPnl, style: const TextStyle(fontSize: 24), showSign: true),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: StatCard(
                        label: 'Open Positions',
                        child: Text(
                          '${data.summary.openPositions}',
                          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600, color: AppColors.textPrimary),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: StatCard(
                        label: 'Unrealized P&L',
                        child: PnlText(data.summary.totalUnrealizedPnl, style: const TextStyle(fontSize: 18)),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: StatCard(
                        label: 'Realized P&L',
                        child: PnlText(data.summary.totalRealizedPnl, style: const TextStyle(fontSize: 18)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 32),
                const Text(
                  'Watchlist & Signals',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 16),
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(32.0),
                    child: Text(
                      'No active signals.',
                      style: TextStyle(color: AppColors.textMuted),
                    ),
                  ),
                )
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _MarketIndexCard extends StatelessWidget {
  const _MarketIndexCard({required this.index});

  final MarketIndex index;

  @override
  Widget build(BuildContext context) {
    final color = index.isUp ? AppColors.profit : AppColors.loss;
    final icon = index.isUp ? Icons.arrow_upward : Icons.arrow_downward;
    
    return Container(
      width: 160,
      margin: const EdgeInsets.only(right: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            index.name,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.textMuted,
            ),
          ),
          const Spacer(),
          Text(
            formatInr(index.ltp),
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 4),
              Text(
                '${index.change > 0 ? "+" : ""}${index.change.toStringAsFixed(1)} (${index.changePct.toStringAsFixed(2)}%)',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: color,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
