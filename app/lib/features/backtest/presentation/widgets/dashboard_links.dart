import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../../core/config/app_config.dart';

/// Deep-links into the OpenSearch backtest/coverage dashboards (`task
/// search:up` / `search:init`), for analytics beyond what the console shows.
class DashboardLinksButton extends StatelessWidget {
  const DashboardLinksButton({super.key});

  Future<void> _open(String dashboardId) async {
    final uri = Uri.parse('${AppConfig.current.dashboardsBase}/app/dashboards#/view/$dashboardId');
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.insights_outlined),
      tooltip: 'OpenSearch dashboards',
      onSelected: _open,
      itemBuilder: (context) => const [
        PopupMenuItem(value: 'backtest-explorer', child: Text('Backtest Explorer')),
        PopupMenuItem(value: 'data-coverage', child: Text('Data Coverage')),
      ],
    );
  }
}
