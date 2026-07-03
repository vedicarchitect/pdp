import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../application/journal_providers.dart';
import '../domain/journal_models.dart';

class JournalScreen extends ConsumerWidget {
  const JournalScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncDay = ref.watch(journalDayProvider);
    final date = ref.watch(journalDateProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trade Journal'),
        actions: [
          IconButton(
            icon: const Icon(Icons.calendar_today),
            tooltip: 'Select date',
            onPressed: () async {
              final picked = await showDatePicker(
                context: context,
                initialDate: date,
                firstDate: DateTime(2020),
                lastDate: DateTime.now(),
              );
              if (picked != null) {
                ref.read(journalDateProvider.notifier).state = picked;
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.arrow_back_ios),
            tooltip: 'Previous day',
            onPressed: () {
              ref.read(journalDateProvider.notifier).update(
                    (state) => state.subtract(const Duration(days: 1)),
                  );
            },
          ),
          IconButton(
            icon: const Icon(Icons.arrow_forward_ios),
            tooltip: 'Next day',
            onPressed: () {
              ref.read(journalDateProvider.notifier).update(
                    (state) => state.add(const Duration(days: 1)),
                  );
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: asyncDay.when(
        data: (day) => _JournalBody(day: day),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Error: $err')),
      ),
    );
  }
}

class _JournalBody extends ConsumerStatefulWidget {
  final JournalDay day;

  const _JournalBody({required this.day});

  @override
  ConsumerState<_JournalBody> createState() => _JournalBodyState();
}

class _JournalBodyState extends ConsumerState<_JournalBody> {
  late TextEditingController _notesController;
  late List<String> _tags;

  @override
  void initState() {
    super.initState();
    _notesController = TextEditingController(text: widget.day.notes);
    _tags = List.from(widget.day.tags);
  }

  @override
  void didUpdateWidget(covariant _JournalBody oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.day.date != widget.day.date) {
      _notesController.text = widget.day.notes;
      _tags = List.from(widget.day.tags);
    }
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  void _saveMetadata() async {
    try {
      final repo = ref.read(journalRepositoryProvider);
      await repo.updateMetadata(
        widget.day.date,
        _notesController.text,
        _tags,
        widget.day.screenshots,
      );
      ref.invalidate(journalDayProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Journal saved')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Save failed: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _buildStatsOverview(context),
        const SizedBox(height: 16),
        _buildEditor(context),
        const SizedBox(height: 16),
        _buildTradeList(context),
      ],
    );
  }

  Widget _buildStatsOverview(BuildContext context) {
    final s = widget.day.stats;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Daily Stats', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _StatText('Trades', '${s.totalTrades}'),
                _StatText('Realized P&L', '\$${s.realizedPnl.toStringAsFixed(2)}',
                    color: s.realizedPnl >= 0 ? Colors.green : Colors.red),
                _StatText('Win Rate', '${(s.winRate * 100).toStringAsFixed(1)}%'),
                _StatText('Charges', '\$${s.totalCharges.toStringAsFixed(2)}'),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEditor(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Notes & Tags', style: Theme.of(context).textTheme.titleLarge),
                FilledButton.icon(
                  onPressed: _saveMetadata,
                  icon: const Icon(Icons.save),
                  label: const Text('Save'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                ..._tags.map(
                  (t) => Chip(
                    label: Text(t),
                    onDeleted: () {
                      setState(() {
                        _tags.remove(t);
                      });
                    },
                  ),
                ),
                ActionChip(
                  label: const Text('Add Tag'),
                  avatar: const Icon(Icons.add, size: 16),
                  onPressed: () async {
                    final newTag = await showDialog<String>(
                      context: context,
                      builder: (c) {
                        String val = '';
                        return AlertDialog(
                          title: const Text('Add Tag'),
                          content: TextField(
                            autofocus: true,
                            onChanged: (v) => val = v,
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(c, null),
                              child: const Text('Cancel'),
                            ),
                            TextButton(
                              onPressed: () => Navigator.pop(c, val),
                              child: const Text('Add'),
                            ),
                          ],
                        );
                      },
                    );
                    if (newTag != null && newTag.isNotEmpty) {
                      setState(() {
                        _tags.add(newTag);
                      });
                    }
                  },
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _notesController,
              maxLines: 5,
              decoration: const InputDecoration(
                hintText: 'Write your daily reflection...',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTradeList(BuildContext context) {
    final trades = widget.day.trades;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Trade Log', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            if (trades.isEmpty)
              const Padding(
                padding: EdgeInsets.all(16.0),
                child: Text('No trades logged for this day.'),
              )
            else
              ListView.separated(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: trades.length,
                separatorBuilder: (c, i) => const Divider(),
                itemBuilder: (c, i) {
                  final t = trades[i];
                  final isBuy = t.side.toUpperCase() == 'BUY';
                  return ListTile(
                    title: Text(t.securityId,
                        style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text('Qty: ${t.qty} @ \$${t.fillPrice.toStringAsFixed(2)}'),
                    trailing: Text(
                      t.side.toUpperCase(),
                      style: TextStyle(
                        color: isBuy ? Colors.green : Colors.red,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  );
                },
              ),
          ],
        ),
      ),
    );
  }
}

class _StatText extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;

  const _StatText(this.label, this.value, {this.color});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
      ],
    );
  }
}
