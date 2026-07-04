import 'package:flutter/material.dart';

import 'advisory_tab.dart';
import 'holdings_tab.dart';

/// Holdings: real stock/ETF holdings (synced from Dhan) with per-stock detail
/// on one tab and sector allocation / advice / P&L history insights on the
/// other. F&O strategy positions live on the Risk & Positions screen instead.
class PortfolioScreen extends StatelessWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Holdings'),
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.pie_chart_outline), text: 'Holdings'),
              Tab(icon: Icon(Icons.lightbulb_outline), text: 'Insights'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            HoldingsTab(),
            AdvisoryTab(),
          ],
        ),
      ),
    );
  }
}
