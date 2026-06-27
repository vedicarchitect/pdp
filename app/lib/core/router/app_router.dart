import 'package:go_router/go_router.dart';

import '../../features/portfolio/presentation/portfolio_screen.dart';
import '../../features/shell/app_shell.dart';
import '../../features/shell/placeholder_screen.dart';

/// Top-level router. A single [ShellRoute] wraps every screen in [AppShell] so
/// navigation chrome stays mounted across route changes.
final GoRouter appRouter = GoRouter(
  initialLocation: '/portfolio',
  routes: [
    ShellRoute(
      builder: (context, state, child) => AppShell(child: child),
      routes: [
        GoRoute(
          path: '/portfolio',
          builder: (context, state) => const PortfolioScreen(),
        ),
        GoRoute(
          path: '/more',
          builder: (context, state) => const PlaceholderScreen(),
        ),
      ],
    ),
  ],
);
