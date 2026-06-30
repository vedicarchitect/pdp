import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/manage_providers.dart';

class HousekeepingTab extends ConsumerWidget {
  const HousekeepingTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        _TaskTile(
          title: 'Backfill Spot Data',
          description: 'Fetch historical spot prices for indices.',
          icon: Icons.history,
          taskName: 'backfill-spot',
          params: {},
        ),
        _TaskTile(
          title: 'Backfill Options Data',
          description: 'Fetch historical options data for backtesting.',
          icon: Icons.auto_graph,
          taskName: 'backfill-options',
          params: {},
        ),
        _TaskTile(
          title: 'Validate Warehouse',
          description: 'Check data integrity in the backtest warehouse.',
          icon: Icons.verified,
          taskName: 'validate-warehouse',
          params: {},
        ),
        _TaskTile(
          title: 'Snapshot Instruments',
          description: 'Update instrument master database.',
          icon: Icons.camera_alt,
          taskName: 'snapshot-instruments',
          params: {},
        ),
        _TaskTile(
          title: 'Reset Paper Trading',
          description: 'WARNING: Delete all paper orders, trades, and positions.',
          icon: Icons.warning,
          taskName: 'reset-paper',
          params: {'confirm': true},
          isDestructive: true,
        ),
      ],
    );
  }
}

class _TaskTile extends ConsumerStatefulWidget {
  final String title;
  final String description;
  final IconData icon;
  final String taskName;
  final Map<String, dynamic> params;
  final bool isDestructive;

  const _TaskTile({
    required this.title,
    required this.description,
    required this.icon,
    required this.taskName,
    required this.params,
    this.isDestructive = false,
  });

  @override
  ConsumerState<_TaskTile> createState() => _TaskTileState();
}

class _TaskTileState extends ConsumerState<_TaskTile> {
  bool _isLoading = false;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        leading: Icon(widget.icon, color: widget.isDestructive ? Colors.red : null),
        title: Text(widget.title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(widget.description),
        trailing: _isLoading 
            ? const CircularProgressIndicator() 
            : FilledButton(
                style: widget.isDestructive ? FilledButton.styleFrom(backgroundColor: Colors.red) : null,
                onPressed: () async {
                  if (widget.isDestructive) {
                    final confirm = await showDialog<bool>(
                      context: context,
                      builder: (c) => AlertDialog(
                        title: const Text('Confirm'),
                        content: const Text('Are you sure you want to run this task? This cannot be undone.'),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                          FilledButton(
                            style: FilledButton.styleFrom(backgroundColor: Colors.red),
                            onPressed: () => Navigator.pop(c, true), 
                            child: const Text('Confirm'),
                          ),
                        ],
                      ),
                    );
                    if (confirm != true) return;
                  }

                  setState(() => _isLoading = true);
                  try {
                    await ref.read(manageRepositoryProvider).runHousekeeping(widget.taskName, widget.params);
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${widget.title} started')));
                    }
                    // Refresh jobs list to show the new task
                    ref.invalidate(jobsProvider);
                  } catch (e) {
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
                    }
                  } finally {
                    if (mounted) setState(() => _isLoading = false);
                  }
                },
                child: const Text('Run'),
              ),
      ),
    );
  }
}
