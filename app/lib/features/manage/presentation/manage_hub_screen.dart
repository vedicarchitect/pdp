import 'package:flutter/material.dart';

import 'tabs/housekeeping_tab.dart';
import 'tabs/jobs_tab.dart';
import 'tabs/journal_tab.dart';
import 'tabs/strategy_tab.dart';

class ManageHubScreen extends StatelessWidget {
  const ManageHubScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Management Hub'),
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.psychology), text: 'Strategies'),
              Tab(icon: Icon(Icons.book), text: 'Journal'),
              Tab(icon: Icon(Icons.cleaning_services), text: 'Housekeeping'),
              Tab(icon: Icon(Icons.engineering), text: 'Jobs / Audit'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            StrategyTab(),
            JournalTab(),
            HousekeepingTab(),
            JobsTab(),
          ],
        ),
      ),
    );
  }
}
