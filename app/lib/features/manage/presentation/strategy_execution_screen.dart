import 'package:flutter/material.dart';

import 'tabs/strategy_execution_tab.dart';

/// Standalone full-screen view of the strategy execution monitor.
/// Exposed as a top-level sidebar nav destination (/execution).
class StrategyExecutionScreen extends StatelessWidget {
  const StrategyExecutionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: StrategyExecutionTab(),
    );
  }
}
