import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../application/events_providers.dart';

class EventConfigDialog extends ConsumerWidget {
  const EventConfigDialog({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stream = ref.watch(eventsStreamProvider);

    return Dialog(
      backgroundColor: AppColors.background,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Container(
        width: 400,
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Event Preferences',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            const SizedBox(height: 16),
            stream.when(
              data: (data) => _buildConfigList(context, ref, data.config),
              error: (e, _) => Text('Error: $e', style: const TextStyle(color: AppColors.loss)),
              loading: () => const Center(child: CircularProgressIndicator()),
            ),
            const SizedBox(height: 24),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => Navigator.of(context).pop(),
                style: TextButton.styleFrom(foregroundColor: AppColors.textPrimary),
                child: const Text('Close'),
              ),
            )
          ],
        ),
      ),
    );
  }

  Widget _buildConfigList(BuildContext context, WidgetRef ref, config) {
    final source = ref.read(eventsSourceProvider);
    final types = config.eventTypePush.keys.toList()..sort();

    return Column(
      children: [
        for (final type in types)
          SwitchListTile(
            title: Text(
              type.toUpperCase(),
              style: const TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w600),
            ),
            activeTrackColor: AppColors.profitFaint,
            activeThumbColor: AppColors.profit,
            value: config.eventTypePush[type] ?? false,
            onChanged: (val) {
              source.patchConfig(eventType: type, pushEnabled: val);
            },
          )
      ],
    );
  }
}
