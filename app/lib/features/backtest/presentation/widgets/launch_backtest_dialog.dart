import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../application/backtest_providers.dart';

class LaunchBacktestDialog extends ConsumerStatefulWidget {
  const LaunchBacktestDialog({super.key});

  @override
  ConsumerState<LaunchBacktestDialog> createState() => _LaunchBacktestDialogState();
}

class _LaunchBacktestDialogState extends ConsumerState<LaunchBacktestDialog> {
  final _formKey = GlobalKey<FormState>();
  final _configController = TextEditingController(text: '{\n  "strategy": "strangle",\n  "st": [10, 2],\n  "tf": [5, 15]\n}');
  
  String _jobType = 'single';
  DateTime _dateFrom = DateTime.now().subtract(const Duration(days: 30));
  DateTime _dateTo = DateTime.now();
  bool _submitting = false;

  Future<void> _pickDate(bool isFrom) async {
    final date = await showDatePicker(
      context: context,
      initialDate: isFrom ? _dateFrom : _dateTo,
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (date != null) {
      setState(() {
        if (isFrom) {
          _dateFrom = date;
        } else {
          _dateTo = date;
        }
      });
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _submitting = true);
    
    try {
      final config = jsonDecode(_configController.text) as Map<String, dynamic>;
      final dateFromStr = DateFormat('yyyy-MM-dd').format(_dateFrom);
      final dateToStr = DateFormat('yyyy-MM-dd').format(_dateTo);
      
      final repo = ref.read(backtestRepositoryProvider);
      
      if (_jobType == 'single') {
        await repo.launchSingle({
          'config': config,
          'date_from': dateFromStr,
          'date_to': dateToStr,
        });
      } else if (_jobType == 'sweep') {
        await repo.launchSweep({
          'config': config,
          'date_from': dateFromStr,
          'date_to': dateToStr,
          'grid': {}, // basic UI doesn't support complex grid yet
        });
      } else if (_jobType == 'walkforward') {
        await repo.launchWalkforward({
          'config': config,
          'date_from': dateFromStr,
          'date_to': dateToStr,
        });
      }
      
      if (mounted) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Launched $_jobType job')),
        );
        ref.invalidate(backtestRunsProvider);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('yyyy-MM-dd');

    return AlertDialog(
      title: const Text('Launch Backtest'),
      content: SizedBox(
        width: 500,
        child: Form(
          key: _formKey,
          child: ListView(
            shrinkWrap: true,
            children: [
              DropdownButtonFormField<String>(
                initialValue: _jobType,
                decoration: const InputDecoration(labelText: 'Job Type'),
                items: const [
                  DropdownMenuItem(value: 'single', child: Text('Single Run')),
                  DropdownMenuItem(value: 'sweep', child: Text('Parameter Sweep')),
                  DropdownMenuItem(value: 'walkforward', child: Text('Walk-forward Optimization')),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _jobType = val);
                },
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: ListTile(
                      title: const Text('Date From'),
                      subtitle: Text(dateFormat.format(_dateFrom)),
                      trailing: const Icon(Icons.calendar_today),
                      onTap: () => _pickDate(true),
                    ),
                  ),
                  Expanded(
                    child: ListTile(
                      title: const Text('Date To'),
                      subtitle: Text(dateFormat.format(_dateTo)),
                      trailing: const Icon(Icons.calendar_today),
                      onTap: () => _pickDate(false),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _configController,
                decoration: const InputDecoration(
                  labelText: 'JSON Config',
                  border: OutlineInputBorder(),
                ),
                maxLines: 8,
                validator: (val) {
                  if (val == null || val.isEmpty) return 'Config is required';
                  try {
                    jsonDecode(val);
                  } catch (e) {
                    return 'Invalid JSON';
                  }
                  return null;
                },
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Launch'),
        ),
      ],
    );
  }
}
