import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../format.dart';

/// A P&L amount that colours itself green (≥ 0) or red (< 0) and animates the
/// colour subtly when the sign changes. Uses tabular figures so digits don't
/// jitter as values tick.
class PnlText extends StatelessWidget {
  const PnlText(
    this.value, {
    super.key,
    this.style,
    this.showSign = true,
  });

  final double value;
  final TextStyle? style;
  final bool showSign;

  @override
  Widget build(BuildContext context) {
    final color = value < 0 ? AppColors.loss : AppColors.profit;
    final baseStyle = style ?? DefaultTextStyle.of(context).style;
    return AnimatedDefaultTextStyle(
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
      style: baseStyle.copyWith(
        color: color,
        fontFeatures: const [FontFeature.tabularFigures()],
      ),
      child: Text(formatInr(value, showSign: showSign)),
    );
  }
}
