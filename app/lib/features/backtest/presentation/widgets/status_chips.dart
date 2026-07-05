import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';

Color _chipColor(String label) {
  switch (label.toUpperCase()) {
    case 'PASS':
    case 'COMPLETED':
    case 'PROMOTED':
      return AppColors.profit;
    case 'REVIEW':
    case 'WARNING':
      return AppColors.warning;
    case 'FAILED':
    case 'REJECTED':
      return AppColors.loss;
    case 'RUNNING':
    case 'PENDING':
      return AppColors.info;
    default:
      return AppColors.neutral;
  }
}

/// A small pill badge used for verdicts, promotion state, and job status —
/// colour comes from [AppColors], never inline.
class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, this.color});

  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? _chipColor(label);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: c.withValues(alpha: 0.4)),
      ),
      child: Text(
        label,
        style: TextStyle(color: c, fontWeight: FontWeight.w600, fontSize: 12),
      ),
    );
  }
}

/// Verdict chip: PASS (profit), REVIEW (warning), or a neutral dash if null.
class VerdictChip extends StatelessWidget {
  const VerdictChip(this.verdict, {super.key});

  final String? verdict;

  @override
  Widget build(BuildContext context) {
    if (verdict == null) return const StatusChip('—', color: AppColors.neutral);
    return StatusChip(verdict!);
  }
}
