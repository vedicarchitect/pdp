import 'package:flutter/painting.dart';

/// Single source of truth for the app palette. Never inline a colour literal in
/// a widget — add it here and reference it.
abstract final class AppColors {
  /// Deep navy base background.
  static const background = Color(0xFF0F172A);

  /// Card / elevated surface.
  static const surface = Color(0xFF1E2937);

  /// Slightly lighter surface for nested rows / chips.
  static const surfaceAlt = Color(0xFF273449);

  /// Profit / positive.
  static const profit = Color(0xFF22C55E);

  /// Loss / negative.
  static const loss = Color(0xFFEF4444);

  /// Translucent fills for chart areas (avoids runtime opacity calls).
  static const profitFaint = Color(0x2922C55E);
  static const lossFaint = Color(0x29EF4444);

  static const textPrimary = Color(0xFFF1F5F9);
  static const textMuted = Color(0xFF94A3B8);
  static const border = Color(0xFF334155);

  /// Warning amber (paper-mode badge).
  static const warning = Color(0xFFF59E0B);
}
