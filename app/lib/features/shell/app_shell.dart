import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../shared/widgets/connection_badge.dart';
import '../../shared/widgets/mode_badge.dart';
import '../events/presentation/event_feed_sidebar.dart';
import '../portfolio/application/portfolio_providers.dart';

/// Responsive app shell: a side [NavigationRail] on wide layouts (desktop /
/// tablet) and a bottom [NavigationBar] on compact layouts (phones).
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  static const double _wideBreakpoint = 720;

  static const List<_Destination> _destinations = [
    _Destination(
      route: '/dashboard',
      label: 'Dashboard',
      icon: Icons.dashboard_outlined,
      selectedIcon: Icons.dashboard,
    ),
    _Destination(
      route: '/portfolio',
      label: 'Holdings',
      icon: Icons.account_balance_wallet_outlined,
      selectedIcon: Icons.account_balance_wallet,
    ),
    _Destination(
      route: '/execution',
      label: 'Execution',
      icon: Icons.play_circle_outline,
      selectedIcon: Icons.play_circle,
    ),
    _Destination(
      route: '/backtests',
      label: 'Backtests',
      icon: Icons.science_outlined,
      selectedIcon: Icons.science,
    ),
    _Destination(
      route: '/intel',
      label: 'Intel',
      icon: Icons.public_outlined,
      selectedIcon: Icons.public,
    ),
    _Destination(
      route: '/journal',
      label: 'Journal',
      icon: Icons.book_outlined,
      selectedIcon: Icons.book,
    ),
    _Destination(
      route: '/screener',
      label: 'Screener',
      icon: Icons.filter_alt_outlined,
      selectedIcon: Icons.filter_alt,
    ),
    _Destination(
      route: '/risk',
      label: 'Risk',
      icon: Icons.gpp_maybe_outlined,
      selectedIcon: Icons.gpp_maybe,
    ),
    _Destination(
      route: '/manage',
      label: 'More',
      icon: Icons.grid_view_outlined,
      selectedIcon: Icons.grid_view,
    ),
  ];

  int _indexFor(String location) {
    final i = _destinations.indexWhere((d) => location.startsWith(d.route));
    return i < 0 ? 0 : i;
  }

  void _onSelect(BuildContext context, int index) {
    context.go(_destinations[index].route);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final location = GoRouterState.of(context).uri.path;
    final index = _indexFor(location);
    final isWide = MediaQuery.sizeOf(context).width >= _wideBreakpoint;
    final mode = ref.watch(modeProvider);

    final appBar = AppBar(
      title: const Text(
        'PDP',
        style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 0.5),
      ),
      actions: [
        ModeBadge(mode: mode),
        const SizedBox(width: 12),
        const ConnectionBadge(),
        if (!isWide) ...[
          const SizedBox(width: 8),
          Builder(
            builder: (context) => IconButton(
              icon: const Icon(Icons.notifications_outlined),
              tooltip: 'Notifications',
              onPressed: () => Scaffold.of(context).openEndDrawer(),
            ),
          ),
        ],
        const SizedBox(width: 16),
      ],
    );

    if (isWide) {
      return Scaffold(
        appBar: appBar,
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: index,
              onDestinationSelected: (i) => _onSelect(context, i),
              labelType: NavigationRailLabelType.all,
              groupAlignment: -0.9,
              destinations: [
                for (final d in _destinations)
                  NavigationRailDestination(
                    icon: Icon(d.icon),
                    selectedIcon: Icon(d.selectedIcon),
                    label: Text(d.label),
                  ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: child),
            const VerticalDivider(width: 1),
            const EventFeedSidebar(),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: appBar,
      body: child,
      endDrawer: const Drawer(
        child: EventFeedSidebar(),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => _onSelect(context, i),
        destinations: [
          for (final d in _destinations)
            NavigationDestination(
              icon: Icon(d.icon),
              selectedIcon: Icon(d.selectedIcon),
              label: d.label,
            ),
        ],
      ),
    );
  }
}

class _Destination {
  const _Destination({
    required this.route,
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });

  final String route;
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}
