import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/manage_providers.dart';

class StrategyTab extends ConsumerWidget {
  const StrategyTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final strategiesAsync = ref.watch(strategiesProvider);

    return strategiesAsync.when(
      data: (strategies) {
        if (strategies.isEmpty) {
          return const Center(child: Text('No strategies found.'));
        }
        return ListView.builder(
          padding: const EdgeInsets.all(16),
          itemCount: strategies.length,
          itemBuilder: (context, index) {
            final strategy = strategies[index];
            final isRunning = strategy.status.toUpperCase() == 'RUNNING';

            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              child: ListTile(
                leading: CircleAvatar(
                  backgroundColor: isRunning ? Colors.green.withValues(alpha: 0.2) : Colors.grey.withValues(alpha: 0.2),
                  child: Icon(
                    isRunning ? Icons.play_arrow : Icons.stop,
                    color: isRunning ? Colors.green : Colors.grey,
                  ),
                ),
                title: Text(strategy.id, style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text('Instrument: ${strategy.instrument ?? 'N/A'} | Interval: ${strategy.interval ?? 'N/A'}'),
                trailing: FilledButton.tonalIcon(
                  onPressed: () async {
                    final repo = ref.read(manageRepositoryProvider);
                    if (isRunning) {
                      await repo.stopStrategy(strategy.id);
                    } else {
                      await repo.startStrategy(strategy.id);
                    }
                    ref.invalidate(strategiesProvider);
                  },
                  icon: Icon(isRunning ? Icons.stop : Icons.play_arrow),
                  label: Text(isRunning ? 'Stop' : 'Start'),
                  style: FilledButton.styleFrom(
                    backgroundColor: isRunning ? Colors.red.withValues(alpha: 0.1) : Colors.green.withValues(alpha: 0.1),
                    foregroundColor: isRunning ? Colors.red : Colors.green,
                  ),
                ),
              ),
            );
          },
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, stack) => Center(child: Text('Error: $error')),
    );
  }
}
