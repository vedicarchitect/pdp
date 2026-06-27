import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/connection_status.dart';
import '../../core/theme/app_colors.dart';

/// A small dot + label reflecting the live-feed connection state.
class ConnectionBadge extends ConsumerWidget {
  const ConnectionBadge({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(connectionStatusProvider);
    final color = switch (status) {
      ConnStatus.connected => AppColors.profit,
      ConnStatus.connecting => AppColors.warning,
      ConnStatus.reconnecting => AppColors.warning,
      ConnStatus.disconnected => AppColors.loss,
    };
    return Tooltip(
      message: 'Data Feed: ${status.label}',
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            status.label,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
