import 'package:flutter/material.dart';

import 'holdings_tab.dart';
import 'positions_tab.dart'; // We will create this

/// Holdings: real stock/ETF holdings (synced from Dhan) with per-stock detail
/// on one tab and F&O intraday positions on the other.
class PortfolioScreen extends StatelessWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Live Account (Dhan)'),
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.pie_chart_outline), text: 'Holdings'),
              Tab(icon: Icon(Icons.list_alt), text: 'Positions'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            HoldingsTab(),
            PositionsTab(),
          ],
        ),
      ),
    );
  }
}
