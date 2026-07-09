import 'package:flutter/material.dart';

import '../../risk/presentation/kill_switch_button.dart';
import 'tabs/broker_tab.dart';
import 'tabs/daily_pnl_tab.dart';
import 'tabs/strategy_execution_tab.dart';

/// Standalone full-screen view of the strategy execution monitor.
/// Exposed as a top-level sidebar nav destination (/execution).
///
/// Tabs: Positions (system-placed strangle legs, Kite-style Open/Closed +
/// side indicator panel) · Daily P&L · Broker (Dhan) (manual broker view).
class StrategyExecutionScreen extends StatelessWidget {
  const StrategyExecutionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Execution Console'),
          actions: const [KillSwitchButton(), SizedBox(width: 8)],
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.monitor_heart), text: 'Positions'),
              Tab(icon: Icon(Icons.account_balance_wallet), text: 'Daily P&L'),
              Tab(icon: Icon(Icons.account_balance), text: 'Broker (Dhan)'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            StrategyExecutionTab(),
            DailyPnlTab(),
            BrokerTab(),
          ],
        ),
      ),
    );
  }
}
