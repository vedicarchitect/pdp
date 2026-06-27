import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdp_app/core/theme/app_colors.dart';
import 'package:pdp_app/features/portfolio/application/portfolio_providers.dart';
import 'package:pdp_app/features/portfolio/domain/portfolio_snapshot.dart';
import 'package:pdp_app/features/portfolio/domain/portfolio_summary.dart';
import 'package:pdp_app/features/portfolio/domain/position.dart';
import 'package:pdp_app/features/portfolio/presentation/portfolio_screen.dart';
import 'package:pdp_app/shared/widgets/pnl_text.dart';

void main() {
  testWidgets('PnlText is green for profit and red for loss', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(children: [PnlText(1000), PnlText(-500)]),
        ),
      ),
    );

    // Scope to each PnlText's own AnimatedDefaultTextStyle — a Material
    // ancestor also provides one, so match by the widget's value.
    final green = tester.widget<AnimatedDefaultTextStyle>(
      find.descendant(
        of: find.byWidgetPredicate((w) => w is PnlText && w.value == 1000),
        matching: find.byType(AnimatedDefaultTextStyle),
      ),
    );
    final red = tester.widget<AnimatedDefaultTextStyle>(
      find.descendant(
        of: find.byWidgetPredicate((w) => w is PnlText && w.value == -500),
        matching: find.byType(AnimatedDefaultTextStyle),
      ),
    );

    expect(green.style.color, AppColors.profit);
    expect(red.style.color, AppColors.loss);
  });

  testWidgets('PortfolioScreen renders summary totals and position rows',
      (tester) async {
    const snapshot = PortfolioSnapshot(
      summary: PortfolioSummary(
        totalUnrealizedPnl: 500,
        totalRealizedPnl: 250,
        dayPnl: 750,
        openPositions: 2,
        mode: 'paper',
      ),
      positions: [
        Position(
          securityId: '1',
          exchangeSegment: 'NSE_FNO',
          product: 'INTRADAY',
          netQty: -75,
          avgPrice: 100,
          realizedPnl: 0,
          unrealizedPnl: 1200,
          symbol: 'NIFTY 24500 CE',
        ),
        Position(
          securityId: '2',
          exchangeSegment: 'NSE_FNO',
          product: 'INTRADAY',
          netQty: -75,
          avgPrice: 90,
          realizedPnl: 0,
          unrealizedPnl: -400,
          symbol: 'NIFTY 24300 PE',
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          portfolioProvider.overrideWith((ref) => Stream.value(snapshot)),
        ],
        child: const MaterialApp(home: Scaffold(body: PortfolioScreen())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('NIFTY 24500 CE'), findsOneWidget);
    expect(find.text('NIFTY 24300 PE'), findsOneWidget);
    expect(find.text('+₹1,200.00'), findsOneWidget); // profit row
    expect(find.text('-₹400.00'), findsOneWidget); // loss row
  });
}
