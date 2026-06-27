import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';

/// Stand-in for screens not yet built. Each future OpenSpec change replaces a
/// line here with a real route that reuses the portfolio data/provider pattern.
class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen({super.key});

  static const _upcoming = [
    'Order entry',
    'Option chain & analytics',
    'Backtest console',
    'Events & alerts',
    'Operations / ML',
  ];

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.construction, size: 40, color: AppColors.textMuted),
          const SizedBox(height: 12),
          const Text(
            'More screens coming soon',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 8),
          for (final item in _upcoming)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text(
                '• $item',
                style: const TextStyle(color: AppColors.textMuted),
              ),
            ),
        ],
      ),
    );
  }
}
