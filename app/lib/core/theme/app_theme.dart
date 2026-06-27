import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_colors.dart';

/// Builds the single dark theme used across the app.
ThemeData buildAppTheme() {
  final colorScheme = ColorScheme.fromSeed(
    seedColor: AppColors.profit,
    brightness: Brightness.dark,
  ).copyWith(
    surface: AppColors.surface,
    primary: AppColors.profit,
    error: AppColors.loss,
    onSurface: AppColors.textPrimary,
  );

  final base = ThemeData(useMaterial3: true, colorScheme: colorScheme);

  return base.copyWith(
    scaffoldBackgroundColor: AppColors.background,
    canvasColor: AppColors.background,
    dividerColor: AppColors.border,
    textTheme: GoogleFonts.interTextTheme(base.textTheme).apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.background,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
    ),
    // Comfortable density => larger touch targets on both phone and desktop.
    visualDensity: VisualDensity.comfortable,
  );
}
