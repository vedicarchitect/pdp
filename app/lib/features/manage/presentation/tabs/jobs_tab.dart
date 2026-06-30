import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../application/manage_providers.dart';

class JobsTab extends ConsumerWidget {
  const JobsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final jobsAsync = ref.watch(jobsProvider);

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.all(8),
          alignment: Alignment.centerRight,
          child: IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh Jobs',
            onPressed: () => ref.invalidate(jobsProvider),
          ),
        ),
        Expanded(
          child: jobsAsync.when(
            data: (jobs) {
              if (jobs.isEmpty) {
                return const Center(child: Text('No background jobs found.'));
              }
              return ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: jobs.length,
                itemBuilder: (context, index) {
                  final job = jobs[index];
                  final isRunning = job.status == 'RUNNING' || job.status == 'PENDING';
                  final isFailed = job.status == 'FAILED';

                  Color statusColor = Colors.grey;
                  if (isRunning) statusColor = Colors.blue;
                  if (job.status == 'COMPLETED') statusColor = Colors.green;
                  if (isFailed) statusColor = Colors.red;

                  return Card(
                    margin: const EdgeInsets.only(bottom: 12),
                    child: ListTile(
                      title: Text(job.type, style: const TextStyle(fontWeight: FontWeight.bold)),
                      subtitle: Text(
                        'Status: ${job.status}\nCreated: ${DateFormat('yyyy-MM-dd HH:mm').format(job.createdAt)}',
                      ),
                      isThreeLine: true,
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: statusColor.withValues(alpha: 0.2),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(
                              job.status, 
                              style: TextStyle(color: statusColor, fontWeight: FontWeight.bold, fontSize: 12),
                            ),
                          ),
                          const SizedBox(width: 16),
                          PopupMenuButton<String>(
                            onSelected: (action) async {
                              final repo = ref.read(manageRepositoryProvider);
                              try {
                                if (action == 'cancel') {
                                  await repo.cancelJob(job.id);
                                } else if (action == 'delete') {
                                  await repo.deleteJob(job.id);
                                }
                                ref.invalidate(jobsProvider);
                              } catch (e) {
                                if (context.mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
                                }
                              }
                            },
                            itemBuilder: (context) => [
                              if (isRunning)
                                const PopupMenuItem(value: 'cancel', child: Text('Cancel')),
                              if (!isRunning)
                                const PopupMenuItem(value: 'delete', child: Text('Delete', style: TextStyle(color: Colors.red))),
                            ],
                          ),
                        ],
                      ),
                    ),
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
