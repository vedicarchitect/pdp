import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../portfolio/application/portfolio_providers.dart';
import '../../portfolio/domain/portfolio_snapshot.dart';
import '../../portfolio/domain/position.dart';
import '../application/risk_providers.dart';
import '../domain/risk_models.dart';

class RiskPositionsScreen extends ConsumerWidget {
  const RiskPositionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statusAsync = ref.watch(dailyLossStatusProvider);
    final settingsAsync = ref.watch(riskSettingsProvider);
    final portfolioAsync = ref.watch(portfolioProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Risk & Positions'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(dailyLossStatusProvider);
            },
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: statusAsync.when(
        data: (status) => settingsAsync.when(
          data: (settings) => _RiskBody(
            status: status,
            settings: settings,
            portfolioAsync: portfolioAsync,
          ),
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (err, _) => Center(child: Text('Error: $err')),
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Error: $err')),
      ),
    );
  }
}

class _RiskBody extends ConsumerWidget {
  final DailyLossStatus status;
  final RiskSettings settings;
  final AsyncValue<PortfolioSnapshot> portfolioAsync;

  const _RiskBody({
    required this.status,
    required this.settings,
    required this.portfolioAsync,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _buildRiskDashboard(context, ref),
        const SizedBox(height: 16),
        _buildPositionsList(context, ref),
      ],
    );
  }

  Widget _buildRiskDashboard(BuildContext context, WidgetRef ref) {
    final loss = status.netTotalPnl < 0 ? -status.netTotalPnl : 0.0;
    final cap = settings.riskDailyLossCapInr;
    final softCap = (settings.riskSoftCapPct / 100.0) * cap;

    final progress = cap > 0 ? (loss / cap).clamp(0.0, 1.0) : 0.0;
    final softCapProgress = cap > 0 ? (softCap / cap) : 0.0;
    
    final isBreached = loss >= cap;
    final isSoftBreached = loss >= softCap;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Daily Loss Status', style: Theme.of(context).textTheme.titleLarge),
                ElevatedButton.icon(
                  onPressed: () => _triggerKillSwitch(context, ref),
                  icon: const Icon(Icons.warning_amber, color: Colors.white),
                  label: const Text('KILL SWITCH', style: TextStyle(color: Colors.white)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.red.shade700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text('Current Loss: \$${loss.toStringAsFixed(2)} / Cap: \$${cap.toStringAsFixed(2)}'),
            const SizedBox(height: 8),
            Stack(
              children: [
                LinearProgressIndicator(
                  value: progress,
                  minHeight: 20,
                  backgroundColor: Colors.grey.shade300,
                  color: isBreached ? Colors.red : (isSoftBreached ? Colors.orange : Colors.green),
                ),
                if (softCapProgress > 0)
                  Positioned(
                    left: 0,
                    right: 0,
                    top: 0,
                    bottom: 0,
                    child: FractionallySizedBox(
                      alignment: Alignment.centerLeft,
                      widthFactor: softCapProgress,
                      child: Container(
                        decoration: BoxDecoration(
                          border: Border(
                            right: BorderSide(
                              color: Colors.black.withValues(alpha: 0.5),
                              width: 2,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('0', style: TextStyle(fontSize: 12)),
                Text('Soft Cap (\$${softCap.toStringAsFixed(0)})', style: const TextStyle(fontSize: 12)),
                Text('Hard Cap (\$${cap.toStringAsFixed(0)})', style: const TextStyle(fontSize: 12)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  void _triggerKillSwitch(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Confirm Kill Switch'),
        content: const Text(
            'This will cancel all open orders and flatten all intraday positions immediately.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancel')),
          TextButton(
            onPressed: () async {
              Navigator.pop(c);
              try {
                await ref.read(riskRepositoryProvider).triggerKillSwitch();
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Kill switch activated successfully.')),
                  );
                  ref.invalidate(dailyLossStatusProvider);
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Failed: $e')),
                  );
                }
              }
            },
            child: const Text('EXECUTE', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }

  Widget _buildPositionsList(BuildContext context, WidgetRef ref) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Active Positions & Risk Rules', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            portfolioAsync.when(
              data: (portfolio) {
                final positions = portfolio.positions;
                if (positions.isEmpty) {
                  return const Text('No open positions.');
                }
                return ListView.separated(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  itemCount: positions.length,
                  separatorBuilder: (_, __) => const Divider(),
                  itemBuilder: (c, i) => _PositionRiskTile(position: positions[i]),
                );
              },
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (err, _) => Text('Error loading positions: $err'),
            ),
          ],
        ),
      ),
    );
  }
}

class _PositionRiskTile extends ConsumerStatefulWidget {
  final Position position;

  const _PositionRiskTile({required this.position});

  @override
  ConsumerState<_PositionRiskTile> createState() => _PositionRiskTileState();
}

class _PositionRiskTileState extends ConsumerState<_PositionRiskTile> {
  bool _expanded = false;
  final _slController = TextEditingController();
  final _targetController = TextEditingController();
  final _trailController = TextEditingController();

  @override
  void dispose() {
    _slController.dispose();
    _targetController.dispose();
    _trailController.dispose();
    super.dispose();
  }

  void _saveRiskParams() async {
    final sl = double.tryParse(_slController.text);
    final t = double.tryParse(_targetController.text);
    final trail = double.tryParse(_trailController.text);

    try {
      await ref.read(riskRepositoryProvider).modifyPositionRisk(
            widget.position.securityId,
            stopLoss: sl,
            target: t,
            trailingSl: trail,
          );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Risk parameters updated.')),
        );
        setState(() {
          _expanded = false;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.position;
    final isLong = p.netQty > 0;
    
    return Column(
      children: [
        ListTile(
          title: Text(p.securityId, style: const TextStyle(fontWeight: FontWeight.bold)),
          subtitle: Text('Qty: ${p.netQty} @ \$${p.avgPrice.toStringAsFixed(2)}'),
          trailing: IconButton(
            icon: Icon(
              _expanded ? Icons.expand_less : Icons.expand_more,
              color: isLong ? Colors.green : Colors.red,
            ),
            onPressed: () => setState(() => _expanded = !_expanded),
          ),
        ),
        if (_expanded)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _slController,
                        decoration: const InputDecoration(
                          labelText: 'Stop Loss',
                          border: OutlineInputBorder(),
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextField(
                        controller: _targetController,
                        decoration: const InputDecoration(
                          labelText: 'Target',
                          border: OutlineInputBorder(),
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextField(
                        controller: _trailController,
                        decoration: const InputDecoration(
                          labelText: 'Trail by (pts)',
                          border: OutlineInputBorder(),
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    OutlinedButton(
                      onPressed: () => setState(() => _expanded = false),
                      child: const Text('Cancel'),
                    ),
                    const SizedBox(width: 8),
                    FilledButton(
                      onPressed: _saveRiskParams,
                      child: const Text('Save'),
                    ),
                  ],
                ),
              ],
            ),
          ),
      ],
    );
  }
}
