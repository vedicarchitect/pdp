import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../application/events_providers.dart';
import '../domain/events_models.dart';
import 'event_config_dialog.dart';

class EventFeedSidebar extends ConsumerWidget {
  const EventFeedSidebar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stream = ref.watch(eventsStreamProvider);

    return Container(
      width: 300,
      color: AppColors.surface,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Row(
              children: [
                const Icon(Icons.notifications_active, color: AppColors.textPrimary, size: 20),
                const SizedBox(width: 8),
                const Text(
                  'Live Events',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textPrimary,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.settings, color: AppColors.textMuted, size: 20),
                  onPressed: () {
                    showDialog(
                      context: context,
                      builder: (_) => const EventConfigDialog(),
                    );
                  },
                )
              ],
            ),
          ),
          const Divider(height: 1, color: AppColors.border),
          Expanded(
            child: stream.when(
              data: (data) => _buildList(data.events),
              error: (e, _) => Center(child: Text('Error: $e', style: const TextStyle(color: AppColors.loss))),
              loading: () => const Center(child: CircularProgressIndicator()),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildList(List<AppEvent> events) {
    if (events.isEmpty) {
      return const Center(
        child: Text(
          'No events to show.',
          style: TextStyle(color: AppColors.textMuted),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: events.length,
      separatorBuilder: (_, __) => const Divider(height: 1, color: AppColors.border),
      itemBuilder: (context, index) {
        final evt = events[index];
        return _EventTile(event: evt);
      },
    );
  }
}

class _EventTile extends StatelessWidget {
  const _EventTile({required this.event});

  final AppEvent event;

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;
    switch (event.severity) {
      case 'alert':
        color = AppColors.loss;
        icon = Icons.warning_rounded;
        break;
      case 'warning':
        color = AppColors.warning;
        icon = Icons.info_outline;
        break;
      default:
        color = AppColors.profit;
        icon = Icons.bolt;
    }

    final hr = event.timestamp.hour.toString().padLeft(2, '0');
    final mn = event.timestamp.minute.toString().padLeft(2, '0');
    final timeStr = '$hr:$mn';

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      event.securityId ?? 'SYSTEM',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    Text(
                      timeStr,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.textMuted,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  event.message,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.textMuted,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: color.withAlpha(38),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    event.eventType.toUpperCase(),
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: color,
                    ),
                  ),
                )
              ],
            ),
          )
        ],
      ),
    );
  }
}
