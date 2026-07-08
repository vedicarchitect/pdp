import 'package:go_router/go_router.dart';

import '../../features/backtest/presentation/backtest_console_screen.dart';
import '../../features/backtest/presentation/backtest_detail_screen.dart';
import '../../features/dashboard/presentation/dashboard_screen.dart';
import '../../features/manage/presentation/manage_hub_screen.dart';
import '../../features/manage/presentation/strategy_execution_screen.dart';
import '../../features/portfolio/presentation/portfolio_screen.dart';
import '../../features/intel/presentation/market_intel_screen.dart';
import '../../features/journal/presentation/journal_screen.dart';
import '../../features/risk/presentation/risk_positions_screen.dart';
import '../../features/screener/presentation/screener_screen.dart';
import '../../features/shell/app_shell.dart';
import '../../features/shell/placeholder_screen.dart';

/// Top-level router. A single [ShellRoute] wraps every screen in [AppShell] so
/// navigation chrome stays mounted across route changes.
final GoRouter appRouter = GoRouter(
  initialLocation: '/dashboard',
  routes: [
    ShellRoute(
      builder: (context, state, child) => AppShell(child: child),
      routes: [
        GoRoute(
          path: '/dashboard',
          builder: (context, state) => const DashboardScreen(),
        ),
        GoRoute(
          path: '/portfolio',
          builder: (context, state) => const PortfolioScreen(),
        ),
        GoRoute(
          path: '/backtests',
          builder: (context, state) => const BacktestConsoleScreen(),
          routes: [
            GoRoute(
              path: ':kind/:id',
              builder: (context, state) => BacktestDetailScreen(
                runId: state.pathParameters['id']!,
                kind: state.pathParameters['kind']!,
              ),
            ),
          ],
        ),
        GoRoute(
          path: '/execution',
          builder: (context, state) => const StrategyExecutionScreen(),
        ),
        GoRoute(
          path: '/manage',
          builder: (context, state) => const ManageHubScreen(),
        ),
        GoRoute(
          path: '/intel',
          builder: (context, state) => const MarketIntelScreen(),
        ),
        GoRoute(
          path: '/journal',
          builder: (context, state) => const JournalScreen(),
        ),
        GoRoute(
          path: '/screener',
          builder: (context, state) => const ScreenerScreen(),
        ),
        GoRoute(
          path: '/risk',
          builder: (context, state) => const RiskPositionsScreen(),
        ),
        GoRoute(
          path: '/more',
          builder: (context, state) => const PlaceholderScreen(),
        ),
      ],
    ),
  ],
);
