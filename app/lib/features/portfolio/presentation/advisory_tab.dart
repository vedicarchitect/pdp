import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../application/advisory_providers.dart';
import '../domain/advisory_models.dart';

class AdvisoryTab extends ConsumerWidget {
  const AdvisoryTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        _DemoDataBanner(),
        _HoldingsOverview(),
        SizedBox(height: 24),
        _AllocationAdvice(),
        SizedBox(height: 24),
        _HistoryChart(),
      ],
    );
  }
}

class _DemoDataBanner extends ConsumerWidget {
  const _DemoDataBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final advisoryAsync = ref.watch(advisoryProvider);
    final isMock = advisoryAsync.value?['is_mock'] as bool? ?? false;
    if (!isMock) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.amber.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.amber.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.info_outline, size: 18, color: Colors.amber),
            const SizedBox(width: 8),
            Text(
              'Demo data — connect a broker sync run to see real holdings',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _HoldingsOverview extends ConsumerWidget {
  const _HoldingsOverview();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final advisoryAsync = ref.watch(advisoryProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Holdings Overview', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        advisoryAsync.when(
          data: (data) {
            final holdings = data['holdings'] as List<HoldingOverview>;
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: holdings.map((holding) {
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8.0),
                      child: Row(
                        children: [
                          SizedBox(width: 100, child: Text(holding.sector, style: const TextStyle(fontWeight: FontWeight.bold))),
                          Expanded(
                            child: LinearProgressIndicator(
                              value: holding.percentage / 100,
                              minHeight: 8,
                              backgroundColor: Colors.grey.withValues(alpha: 0.2),
                              color: Theme.of(context).colorScheme.primary,
                            ),
                          ),
                          const SizedBox(width: 16),
                          SizedBox(width: 50, child: Text('${holding.percentage}%', textAlign: TextAlign.right)),
                        ],
                      ),
                    );
                  }).toList(),
                ),
              ),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}

class _AllocationAdvice extends ConsumerWidget {
  const _AllocationAdvice();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final advisoryAsync = ref.watch(advisoryProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Allocation Advice', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        advisoryAsync.when(
          data: (data) {
            final adviceList = data['advice'] as List<AllocationAdvice>;
            return Column(
              children: adviceList.map((advice) {
                final isHigh = advice.severity == 'high';
                return Card(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: isHigh ? Colors.red.withValues(alpha: 0.2) : Colors.orange.withValues(alpha: 0.2),
                      child: Icon(
                        isHigh ? Icons.warning : Icons.lightbulb,
                        color: isHigh ? Colors.red : Colors.orange,
                      ),
                    ),
                    title: Text(advice.title, style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text(advice.description),
                    trailing: FilledButton.tonal(
                      onPressed: () => context.push('/screener'),
                      child: Text(advice.action),
                    ),
                  ),
                );
              }).toList(),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}

class _HistoryChart extends ConsumerWidget {
  const _HistoryChart();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final historyAsync = ref.watch(historyProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Historical P&L (30 Days)', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        historyAsync.when(
          data: (history) {
            if (history.isEmpty) {
              return const Card(
                child: Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: Text('No history yet')),
                ),
              );
            }
            final maxPnl = history.map((e) => e.pnl.abs()).reduce((a, b) => a > b ? a : b);
            
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: SizedBox(
                  height: 100,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: history.map((point) {
                      final isPositive = point.pnl >= 0;
                      final height = (point.pnl.abs() / (maxPnl == 0 ? 1 : maxPnl)) * 80;
                      return Expanded(
                        child: Tooltip(
                          message: '${DateFormat('MMM dd').format(point.date)}\n\$${point.pnl.toStringAsFixed(2)}',
                          child: Container(
                            margin: const EdgeInsets.symmetric(horizontal: 1),
                            height: height == 0 ? 2 : height,
                            color: isPositive ? Colors.green : Colors.red,
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}
