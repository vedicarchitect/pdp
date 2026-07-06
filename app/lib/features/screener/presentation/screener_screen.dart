import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../application/screener_providers.dart';

class ScreenerScreen extends ConsumerWidget {
  const ScreenerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final resultsAsync = ref.watch(screenerResultsProvider);
    final strategy = ref.watch(screenerStrategyProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Screener'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh screener results',
            onPressed: () => ref.invalidate(screenerResultsProvider),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildStrategySelector(context, ref, strategy),
            const SizedBox(height: 16),
            Expanded(
              child: resultsAsync.when(
                data: (results) {
                  if (results.isEmpty) {
                    return const Center(child: Text('No results matched.'));
                  }
                  return ListView.separated(
                    itemCount: results.length,
                    separatorBuilder: (_, __) => const Divider(),
                    itemBuilder: (context, i) {
                      final r = results[i];
                      final isPositive = r.changePct >= 0;
                      return ListTile(
                        title: Text(r.symbol, style: const TextStyle(fontWeight: FontWeight.bold)),
                        subtitle: Text(r.matchingCriteria.join(', ')),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text('\$${r.lastPrice.toStringAsFixed(2)}',
                                    style: const TextStyle(fontWeight: FontWeight.bold)),
                                Text(
                                  '${isPositive ? '+' : ''}${r.changePct.toStringAsFixed(2)}%',
                                  style: TextStyle(
                                      color: isPositive ? Colors.green : Colors.red,
                                      fontSize: 12),
                                ),
                              ],
                            ),
                            const SizedBox(width: 16),
                            FilledButton.icon(
                              onPressed: () {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text('Executing ${r.symbol}... (Mock)')),
                                );
                              },
                              icon: const Icon(Icons.flash_on, size: 16),
                              label: const Text('Execute'),
                            ),
                          ],
                        ),
                      );
                    },
                  );
                },
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (err, _) => Center(child: Text('Error: $err')),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStrategySelector(BuildContext context, WidgetRef ref, String currentStrategy) {
    const strategies = {
      'ema_alignment': 'EMA Alignment',
      '9x20_cross': '9EMA x 20MA Cross',
      'volume_breakout': 'High Volume Breakout',
    };

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
        child: Row(
          children: [
            const Text('Strategy: ', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(width: 16),
            DropdownButton<String>(
              value: currentStrategy,
              underline: const SizedBox(),
              items: strategies.entries
                  .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
                  .toList(),
              onChanged: (val) {
                if (val != null) {
                  ref.read(screenerStrategyProvider.notifier).state = val;
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}
