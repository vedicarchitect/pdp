import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pdp_app/core/theme/app_colors.dart';
import 'package:pdp_app/features/portfolio/application/holdings_providers.dart';
import 'package:pdp_app/features/portfolio/domain/holdings_models.dart';
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

  testWidgets('PortfolioScreen renders holdings summary and per-stock rows',
      (tester) async {
    const summary = HoldingsSummary(
      totalInvested: 82000,
      totalCurrentValue: 100000,
      totalPnl: 18000,
      totalPnlPct: 21.95,
      holdingsCount: 2,
      cashAvailable: 15000,
    );
    const holdings = [
      HoldingDetail(
        symbol: 'TCS',
        exchange: 'NSE',
        sector: 'Technology',
        qty: 20,
        avgPrice: 3200,
        lastPrice: 3800,
        investedValue: 64000,
        currentValue: 76000,
        pnl: 12000,
        pnlPct: 18.75,
      ),
      HoldingDetail(
        symbol: 'SUNPHARMA',
        exchange: 'NSE',
        sector: 'Healthcare',
        qty: 5,
        avgPrice: 900,
        lastPrice: 800,
        investedValue: 4500,
        currentValue: 4000,
        pnl: -500,
        pnlPct: -11.11,
      ),
    ];

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          holdingsProvider.overrideWith(
            (ref) async => {
              'summary': summary,
              'holdings': holdings,
              'is_mock': false,
            },
          ),
        ],
        child: const MaterialApp(home: Scaffold(body: PortfolioScreen())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Holdings'), findsWidgets);
    expect(find.text('TCS'), findsOneWidget);
    expect(find.text('SUNPHARMA'), findsOneWidget);
    expect(find.text('+₹12,000.00'), findsOneWidget); // profit row
    expect(find.text('-₹500.00'), findsOneWidget); // loss row
  });
}
