import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';

final _selectedSweepIdProvider = StateProvider<String?>((ref) => null);

/// Sweep leaderboard: ranked param combinations with the best param
/// highlighted. There is no "list sweeps" endpoint, so recently-launched
/// sweep ids (captured from the launch job result) seed the picker, and a
/// sweep id can also be pasted in directly.
class SweepTab extends ConsumerWidget {
  const SweepTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final recent = ref.watch(recentSweepIdsProvider);
    final selected = ref.watch(_selectedSweepIdProvider);
    final controller = TextEditingController(text: selected ?? '');

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: controller,
                  decoration: const InputDecoration(labelText: 'Sweep ID', hintText: 'e.g. sweep-1720000000000'),
                  onSubmitted: (v) => ref.read(_selectedSweepIdProvider.notifier).state = v.trim(),
                ),
              ),
              const SizedBox(width: 12),
              FilledButton(
                onPressed: () =>
                    ref.read(_selectedSweepIdProvider.notifier).state = controller.text.trim(),
                child: const Text('Load'),
              ),
            ],
          ),
          if (recent.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: recent
                  .map((id) => ActionChip(
                        label: Text(id),
                        onPressed: () => ref.read(_selectedSweepIdProvider.notifier).state = id,
                      ))
                  .toList(growable: false),
            ),
          ],
          const SizedBox(height: 16),
          Expanded(
            child: selected == null || selected.isEmpty
                ? const Center(child: Text('Enter or pick a sweep ID to view its leaderboard.'))
                : _SweepLeaderboard(sweepId: selected),
          ),
        ],
      ),
    );
  }
}

class _SweepLeaderboard extends ConsumerWidget {
  const _SweepLeaderboard({required this.sweepId});

  final String sweepId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sweepAsync = ref.watch(backtestSweepProvider(sweepId));

    return sweepAsync.when(
      data: (sweep) {
        if (sweep.combos.isEmpty) {
          return const Center(child: Text('This sweep has no combinations.'));
        }
        final paramKeys = sweep.combos.first.params.keys.toList(growable: false);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Objective: ${sweep.objective}', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Expanded(
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: [
                    const DataColumn(label: Text('Rank')),
                    ...paramKeys.map((k) => DataColumn(label: Text(k))),
                    const DataColumn(label: Text('PF'), numeric: true),
                    const DataColumn(label: Text('Net'), numeric: true),
                  ],
                  rows: sweep.combos.map((combo) {
                    final isBest = combo.rank == 0;
                    return DataRow(
                      color: isBest
                          ? WidgetStatePropertyAll(AppColors.profit.withValues(alpha: 0.08))
                          : null,
                      cells: [
                        DataCell(Text('${combo.rank + 1}${isBest ? ' ★' : ''}')),
                        ...paramKeys.map((k) => DataCell(Text('${combo.params[k]}'))),
                        DataCell(Text(combo.profitFactor?.toStringAsFixed(2) ?? '-')),
                        DataCell(Text(combo.net?.toStringAsFixed(0) ?? '-')),
                      ],
                    );
                  }).toList(growable: false),
                ),
              ),
            ),
          ],
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
    );
  }
}
