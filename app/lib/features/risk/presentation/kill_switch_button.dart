/// Reusable kill-switch AppBar action. Relocated here from the retired standalone
/// "Risk & Positions" screen so the safety-critical control lives at the trading
/// surface (the Execution Console) rather than a separate nav tab.
library;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../application/risk_providers.dart';

class KillSwitchButton extends ConsumerWidget {
  const KillSwitchButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      tooltip: 'Kill switch — flatten all & halt',
      icon: const Icon(Icons.gpp_maybe, color: Colors.redAccent),
      onPressed: () => _confirm(context, ref),
    );
  }

  void _confirm(BuildContext context, WidgetRef ref) {
    showDialog<void>(
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
                    const SnackBar(content: Text('Kill switch activated.')),
                  );
                }
              } on DioException catch (e) {
                if (context.mounted) {
                  final msg = e.response?.statusCode == 503
                      ? 'Engine offline (503): cannot process kill switch.'
                      : 'Failed: ${e.message}';
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(msg)));
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text('Failed: $e')));
                }
              }
            },
            child: const Text('EXECUTE', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );
  }
}
