import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';
import '../../domain/models.dart';

/// PASS-thresholds enforced server-side (`pdp/backtest/store.py`); shown
/// alongside the run's actual stitched-OOS metrics as promotion rationale.
const _thresholds = {
  'Net P&L': '> 0',
  'Profit factor': '> 1.2',
  'Sharpe': '> 0.5',
  'Positive fold fraction': '≥ 60%',
};

/// Shows the promotion rationale/evidence for a PASS run and confirms with an
/// optional note before calling `POST /runs/{id}/promote`.
class PromoteDialog extends ConsumerStatefulWidget {
  const PromoteDialog({super.key, required this.run});

  final BacktestRun run;

  @override
  ConsumerState<PromoteDialog> createState() => _PromoteDialogState();
}

class _PromoteDialogState extends ConsumerState<PromoteDialog> {
  final _noteController = TextEditingController();
  bool _submitting = false;
  String? _error;

  Future<void> _confirm() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final note = _noteController.text.trim();
      await ref.read(backtestSourceProvider).promoteRun(widget.run.runId, note: note.isEmpty ? null : note);
      ref.invalidate(backtestRunDetailProvider(widget.run.runId));
      ref.invalidate(backtestRunsProvider);
      if (mounted) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Run promoted to paper strategy')));
      }
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final foldsAsync = ref.watch(backtestFoldsProvider(widget.run.runId));

    return AlertDialog(
      title: const Text('Promote to paper'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Required thresholds for a PASS verdict:',
                style: Theme.of(context).textTheme.titleSmall,
              ),
              const SizedBox(height: 8),
              ..._thresholds.entries.map(
                (e) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(child: Text(e.key)),
                      Text(e.value, style: const TextStyle(color: AppColors.textMuted)),
                    ],
                  ),
                ),
              ),
              const Divider(height: 24),
              Text('Actual stitched-OOS metrics', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              foldsAsync.when(
                data: (folds) {
                  final s = folds.stitchedOos;
                  if (s == null) {
                    return Text('Net ${widget.run.net?.toStringAsFixed(0) ?? '-'}, '
                        'PF ${widget.run.profitFactor?.toStringAsFixed(2) ?? '-'}, '
                        'Sharpe ${widget.run.sharpe?.toStringAsFixed(2) ?? '-'}');
                  }
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Net: ${s.net.toStringAsFixed(0)}'),
                      Text('Profit factor: ${s.profitFactor?.toStringAsFixed(2) ?? '-'}'),
                      Text('Sharpe: ${s.sharpe?.toStringAsFixed(2) ?? '-'}'),
                      Text('Positive folds: ${s.positiveFolds}/${s.folds} '
                          '(${(s.positiveFoldFraction * 100).toStringAsFixed(0)}%)'),
                    ],
                  );
                },
                loading: () => const LinearProgressIndicator(),
                error: (e, _) => Text('Could not load fold evidence: $e', style: const TextStyle(color: AppColors.warning)),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _noteController,
                decoration: const InputDecoration(labelText: 'Note (optional)'),
                maxLines: 2,
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: const TextStyle(color: AppColors.loss)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _confirm,
          child: _submitting
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Confirm Promote'),
        ),
      ],
    );
  }
}
