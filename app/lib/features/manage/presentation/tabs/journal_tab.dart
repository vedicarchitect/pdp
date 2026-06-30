import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../application/manage_providers.dart';

class JournalTab extends ConsumerWidget {
  const JournalTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedDate = ref.watch(journalDateProvider);
    final entriesAsync = ref.watch(journalEntriesProvider);
    final statsAsync = ref.watch(journalStatsProvider);

    return Column(
      children: [
        // Date Picker Header
        Container(
          padding: const EdgeInsets.all(16),
          color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.3),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Trades for ${DateFormat('yyyy-MM-dd').format(selectedDate)}',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              OutlinedButton.icon(
                onPressed: () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: selectedDate,
                    firstDate: DateTime(2020),
                    lastDate: DateTime.now(),
                  );
                  if (date != null) {
                    ref.read(journalDateProvider.notifier).state = date;
                  }
                },
                icon: const Icon(Icons.calendar_today, size: 16),
                label: const Text('Change Date'),
              ),
            ],
          ),
        ),
        
        // Stats Summary
        statsAsync.when(
          data: (stats) {
            final double grossPnl = (stats['gross_pnl'] as num?)?.toDouble() ?? 0.0;
            final double netPnl = (stats['net_pnl'] as num?)?.toDouble() ?? 0.0;
            final double charges = (stats['charges'] as num?)?.toDouble() ?? 0.0;
            final int trades = (stats['trades_count'] as num?)?.toInt() ?? 0;

            return Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  _StatBox(title: 'Gross PnL', value: grossPnl, isCurrency: true),
                  const SizedBox(width: 16),
                  _StatBox(title: 'Charges', value: charges, isCurrency: true, color: Colors.red),
                  const SizedBox(width: 16),
                  _StatBox(title: 'Net PnL', value: netPnl, isCurrency: true),
                  const SizedBox(width: 16),
                  _StatBox(title: 'Trades', value: trades.toDouble(), isCurrency: false),
                ],
              ),
            );
          },
          loading: () => const LinearProgressIndicator(),
          error: (_, __) => const SizedBox.shrink(),
        ),

        const Divider(height: 1),

        // Entries List
        Expanded(
          child: entriesAsync.when(
            data: (entries) {
              if (entries.isEmpty) {
                return const Center(child: Text('No trades found for this date.'));
              }
              return ListView.builder(
                itemCount: entries.length,
                itemBuilder: (context, index) {
                  final entry = entries[index];
                  return ListTile(
                    leading: CircleAvatar(
                      backgroundColor: Theme.of(context).colorScheme.primaryContainer,
                      child: Text(entry.type.substring(0, 1).toUpperCase()),
                    ),
                    title: Text(entry.type.toUpperCase()),
                    subtitle: Text(entry.data.toString()),
                    isThreeLine: true,
                  );
                },
              );
            },
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (error, _) => Center(child: Text('Error: $error')),
          ),
        ),
      ],
    );
  }
}

class _StatBox extends StatelessWidget {
  final String title;
  final double value;
  final bool isCurrency;
  final Color? color;

  const _StatBox({
    required this.title,
    required this.value,
    required this.isCurrency,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    final valueColor = color ?? (value >= 0 ? Colors.green : Colors.red);
    final formattedValue = isCurrency 
      ? NumberFormat.currency(symbol: '₹', decimalDigits: 2).format(value)
      : value.toInt().toString();

    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Theme.of(context).dividerColor),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            Text(
              formattedValue, 
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                color: valueColor,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
