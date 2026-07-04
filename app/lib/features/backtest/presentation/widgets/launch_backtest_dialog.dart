import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';
import '../../domain/strategy_info.dart';

const _underlyings = ['NIFTY', 'BANKNIFTY', 'SENSEX'];
const _kinds = ['single', 'sweep', 'walkforward'];

/// Launch flow: strategy picker (registry) → schema-driven param form →
/// window + index + kind → launch as an async job with live progress.
class LaunchBacktestDialog extends ConsumerStatefulWidget {
  const LaunchBacktestDialog({super.key});

  @override
  ConsumerState<LaunchBacktestDialog> createState() => _LaunchBacktestDialogState();
}

class _LaunchBacktestDialogState extends ConsumerState<LaunchBacktestDialog> {
  String _kind = 'single';
  String _underlying = 'NIFTY';
  String? _strategyId;
  final Map<String, Object?> _params = {};
  DateTime _dateFrom = DateTime.now().subtract(const Duration(days: 90));
  DateTime _dateTo = DateTime.now();
  String _objective = 'pf';
  int _isMonths = 12;
  int _oosMonths = 3;
  int _stepMonths = 3;
  final Map<String, String> _gridInputs = {};
  String? _jobId;
  bool _submitting = false;
  String? _error;

  void _applyStrategy(StrategyInfo info) {
    _params
      ..clear()
      ..addAll(info.defaults);
    for (final spec in info.paramsSchema) {
      _params.putIfAbsent(spec.name, () => spec.defaultValue);
    }
    if (info.underlying != null && _underlyings.contains(info.underlying)) {
      _underlying = info.underlying!;
    }
  }

  Future<void> _pickDate(bool isFrom) async {
    final date = await showDatePicker(
      context: context,
      initialDate: isFrom ? _dateFrom : _dateTo,
      firstDate: DateTime(2018),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (date != null) {
      setState(() => isFrom ? _dateFrom = date : _dateTo = date);
    }
  }

  Map<String, dynamic> _buildConfig() {
    return {..._params, 'underlying': _underlying};
  }

  List<Object?> _parseGridValues(ParamSpec spec) {
    final raw = _gridInputs[spec.name];
    if (raw == null || raw.trim().isEmpty) {
      return [_params[spec.name] ?? spec.defaultValue];
    }
    return raw.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).map<Object?>((s) {
      switch (spec.type) {
        case 'bool':
          return s.toLowerCase() == 'true';
        case 'int':
          return int.tryParse(s) ?? s;
        case 'float':
          return double.tryParse(s) ?? s;
        default:
          return s;
      }
    }).toList();
  }

  Future<void> _submit() async {
    if (_strategyId == null) {
      setState(() => _error = 'Select a strategy first');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });

    final source = ref.read(backtestSourceProvider);
    final dateFrom = DateFormat('yyyy-MM-dd').format(_dateFrom);
    final dateTo = DateFormat('yyyy-MM-dd').format(_dateTo);

    try {
      String jobId;
      if (_kind == 'single') {
        jobId = await source.launchSingle({
          'config': _buildConfig(),
          'date_from': dateFrom,
          'date_to': dateTo,
          'mongo': true,
        });
      } else if (_kind == 'sweep') {
        final strategiesAsync = ref.read(strategiesProvider);
        final schema = strategiesAsync.valueOrNull
                ?.firstWhere((s) => s.id == _strategyId, orElse: () => strategiesAsync.value!.first)
                .paramsSchema ??
            const <ParamSpec>[];
        final grid = <String, List<Object?>>{
          for (final spec in schema) spec.name: _parseGridValues(spec),
        };
        jobId = await source.launchSweep({
          'config': _buildConfig(),
          'date_from': dateFrom,
          'date_to': dateTo,
          'grid': grid,
          'objective': _objective,
          'mongo': true,
        });
      } else {
        jobId = await source.launchWalkforward({
          'config': _buildConfig(),
          'date_from': dateFrom,
          'date_to': dateTo,
          'is_months': _isMonths,
          'oos_months': _oosMonths,
          'step_months': _stepMonths,
          'objective': _objective,
          'mongo': true,
        });
      }
      setState(() => _jobId = jobId);
    } catch (e) {
      setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Launch Backtest'),
      content: SizedBox(
        width: 560,
        child: _jobId != null
            ? _JobProgressView(jobId: _jobId!, onClose: () => Navigator.of(context).pop())
            : _buildForm(context),
      ),
      actions: _jobId != null
          ? null
          : [
              TextButton(
                onPressed: _submitting ? null : () => Navigator.of(context).pop(),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Launch'),
              ),
            ],
    );
  }

  Widget _buildForm(BuildContext context) {
    final strategiesAsync = ref.watch(strategiesProvider);
    final dateFormat = DateFormat('yyyy-MM-dd');

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          DropdownButtonFormField<String>(
            initialValue: _kind,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Kind'),
            items: _kinds
                .map((k) => DropdownMenuItem(value: k, child: Text(k, overflow: TextOverflow.ellipsis)))
                .toList(growable: false),
            onChanged: (v) => setState(() => _kind = v ?? _kind),
          ),
          const SizedBox(height: 12),
          strategiesAsync.when(
            data: (strategies) {
              return DropdownButtonFormField<String>(
                key: const Key('strategyDropdown'),
                initialValue: _strategyId,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Strategy'),
                items: strategies
                    .map((s) => DropdownMenuItem(
                          value: s.id,
                          child: Text('${s.id} (${s.source})', overflow: TextOverflow.ellipsis),
                        ))
                    .toList(growable: false),
                onChanged: (id) {
                  final info = strategies.firstWhere((s) => s.id == id);
                  setState(() {
                    _strategyId = id;
                    _applyStrategy(info);
                  });
                },
              );
            },
            loading: () => const LinearProgressIndicator(),
            error: (e, _) => Text('Failed to load strategies: $e', style: const TextStyle(color: AppColors.loss)),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _underlying,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Index'),
            items: _underlyings
                .map((u) => DropdownMenuItem(value: u, child: Text(u, overflow: TextOverflow.ellipsis)))
                .toList(growable: false),
            onChanged: (v) => setState(() => _underlying = v ?? _underlying),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('From'),
                  subtitle: Text(dateFormat.format(_dateFrom)),
                  trailing: const Icon(Icons.calendar_today, size: 18),
                  onTap: () => _pickDate(true),
                ),
              ),
              Expanded(
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('To'),
                  subtitle: Text(dateFormat.format(_dateTo)),
                  trailing: const Icon(Icons.calendar_today, size: 18),
                  onTap: () => _pickDate(false),
                ),
              ),
            ],
          ),
          if (_kind != 'single') ...[
            const SizedBox(height: 4),
            DropdownButtonFormField<String>(
              initialValue: _objective,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Objective'),
              items: const [
                DropdownMenuItem(value: 'pf', child: Text('Profit factor')),
                DropdownMenuItem(value: 'sharpe', child: Text('Sharpe')),
                DropdownMenuItem(value: 'net', child: Text('Net P&L')),
              ],
              onChanged: (v) => setState(() => _objective = v ?? _objective),
            ),
          ],
          if (_kind == 'walkforward') ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(child: _numberField('IS months', _isMonths, (v) => _isMonths = v)),
                const SizedBox(width: 8),
                Expanded(child: _numberField('OOS months', _oosMonths, (v) => _oosMonths = v)),
                const SizedBox(width: 8),
                Expanded(child: _numberField('Step months', _stepMonths, (v) => _stepMonths = v)),
              ],
            ),
          ],
          const SizedBox(height: 16),
          if (_strategyId != null) _buildParamForm(strategiesAsync, context),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: const TextStyle(color: AppColors.loss)),
          ],
        ],
      ),
    );
  }

  Widget _numberField(String label, int value, void Function(int) onChanged) {
    return TextFormField(
      initialValue: '$value',
      decoration: InputDecoration(labelText: label),
      keyboardType: TextInputType.number,
      onChanged: (s) => onChanged(int.tryParse(s) ?? value),
    );
  }

  Widget _buildParamForm(AsyncValue<List<StrategyInfo>> strategiesAsync, BuildContext context) {
    final schema = strategiesAsync.valueOrNull
            ?.firstWhere((s) => s.id == _strategyId)
            .paramsSchema ??
        const <ParamSpec>[];
    if (schema.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Parameters', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        ...schema.map((spec) => _paramField(spec)),
      ],
    );
  }

  Widget _paramField(ParamSpec spec) {
    if (_kind == 'sweep') {
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: TextFormField(
          decoration: InputDecoration(
            labelText: '${spec.name} (comma-separated ${spec.type} values)',
            hintText: '${_params[spec.name]}',
          ),
          onChanged: (v) => _gridInputs[spec.name] = v,
        ),
      );
    }

    switch (spec.type) {
      case 'bool':
        return SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(spec.name),
          value: _params[spec.name] as bool? ?? false,
          onChanged: (v) => setState(() => _params[spec.name] = v),
        );
      case 'int':
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: TextFormField(
            initialValue: '${_params[spec.name]}',
            decoration: InputDecoration(labelText: spec.name),
            keyboardType: TextInputType.number,
            onChanged: (v) => _params[spec.name] = int.tryParse(v),
          ),
        );
      case 'float':
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: TextFormField(
            initialValue: '${_params[spec.name]}',
            decoration: InputDecoration(labelText: spec.name),
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: (v) => _params[spec.name] = double.tryParse(v),
          ),
        );
      default:
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: TextFormField(
            initialValue: '${_params[spec.name] ?? ''}',
            decoration: InputDecoration(labelText: spec.name),
            onChanged: (v) => _params[spec.name] = v,
          ),
        );
    }
  }
}

/// Live job progress inside the launch dialog. On a terminal frame it
/// invalidates [backtestRunsProvider] so the run appears in the console table.
class _JobProgressView extends ConsumerWidget {
  const _JobProgressView({required this.jobId, required this.onClose});

  final String jobId;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progressAsync = ref.watch(jobProgressProvider(jobId));

    return progressAsync.when(
      data: (progress) {
        if (progress.isTerminal) {
          Future.microtask(() async {
            ref.invalidate(backtestRunsProvider);
            if (progress.isCompleted) {
              final job = await ref.read(backtestSourceProvider).getJob(jobId);
              final sweepId = job.result?['sweep_id'] as String?;
              if (sweepId != null) {
                ref.read(recentSweepIdsProvider.notifier).add(sweepId);
              }
            }
          });
        }
        final label = progress.isCompleted
            ? 'Completed'
            : progress.isFailed
                ? progress.message
                : progress.isCancelled
                    ? 'Cancelled'
                    : progress.message.isEmpty
                        ? 'Running…'
                        : progress.message;
        final color = progress.isCompleted
            ? AppColors.profit
            : progress.isFailed
                ? AppColors.loss
                : progress.isCancelled
                    ? AppColors.neutral
                    : AppColors.info;
        return Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            LinearProgressIndicator(value: progress.progress / 100, color: color),
            const SizedBox(height: 12),
            Text('${progress.progress}% — $label', style: TextStyle(color: color)),
            const SizedBox(height: 16),
            if (progress.isTerminal)
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton(onPressed: onClose, child: const Text('Done')),
              ),
          ],
        );
      },
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Text('Job stream error: $e', style: const TextStyle(color: AppColors.loss)),
    );
  }
}
