import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';

/// PAPER (amber) / LIVE (red) badge driven by the backend's reported mode.
class ModeBadge extends StatelessWidget {
  const ModeBadge({super.key, required this.mode});

  /// `'paper'` or `'live'`.
  final String mode;

  @override
  Widget build(BuildContext context) {
    final isLive = mode.toLowerCase() == 'live';
    final color = isLive ? AppColors.loss : AppColors.warning;
    return Tooltip(
      message: isLive ? 'Live Orders Enabled' : 'Paper Trading (Simulated)',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: color.withAlpha(38),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: color),
        ),
        child: Text(
          isLive ? 'LIVE' : 'PAPER',
          style: TextStyle(
            color: color,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.8,
          ),
        ),
      ),
    );
  }
}
