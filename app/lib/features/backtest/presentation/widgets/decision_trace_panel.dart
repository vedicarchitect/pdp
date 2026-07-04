import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';
import '../../domain/models.dart';

/// Reason-coded why-entry/why-exit events by default, with the full
/// per-minute trace loadable on demand for a chosen day.
class DecisionTracePanel extends ConsumerStatefulWidget {
  const DecisionTracePanel({super.key, required this.runId, required this.dates});

  final String runId;
  final List<String> dates;

  @override
  ConsumerState<DecisionTracePanel> createState() => _DecisionTracePanelState();
}

class _DecisionTracePanelState extends ConsumerState<DecisionTracePanel> {
  String? _selectedDate;
  bool _fullTrace = false;

  @override
  Widget build(BuildContext context) {
    final key = (runId: widget.runId, date: _selectedDate, full: false);
    final eventsAsync = ref.watch(backtestDecisionsProvider(key));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              DropdownButton<String?>(
                value: _selectedDate,
                hint: const Text('All dates'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('All dates')),
                  ...widget.dates.map((d) => DropdownMenuItem(value: d, child: Text(d))),
                ],
                onChanged: (v) => setState(() {
                  _selectedDate = v;
                  _fullTrace = false;
                }),
              ),
              const SizedBox(width: 16),
              if (_selectedDate != null)
                OutlinedButton.icon(
                  onPressed: () => setState(() => _fullTrace = !_fullTrace),
                  icon: Icon(_fullTrace ? Icons.unfold_less : Icons.unfold_more),
                  label: Text(_fullTrace ? 'Hide full per-minute trace' : 'Load full per-minute trace'),
                ),
            ],
          ),
        ),
        Expanded(
          child: eventsAsync.when(
            data: (events) {
              if (events.isEmpty) {
                return const Center(child: Text('No decision events recorded.'));
              }
              return ListView.builder(
                itemCount: events.length,
                itemBuilder: (context, i) => _DecisionTile(event: events[i]),
              );
            },
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
          ),
        ),
        if (_selectedDate != null && _fullTrace)
          Expanded(
            child: _FullTraceView(runId: widget.runId, date: _selectedDate!),
          ),
      ],
    );
  }
}

class _DecisionTile extends StatelessWidget {
  const _DecisionTile({required this.event});

  final DecisionEvent event;

  Color get _eventColor {
    switch (event.event) {
      case 'entry':
      case 'reentry':
        return AppColors.profit;
      case 'exit':
        return AppColors.loss;
      case 'scale_in':
      case 'rollup':
        return AppColors.info;
      default:
        return AppColors.neutral;
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      leading: CircleAvatar(
        radius: 6,
        backgroundColor: _eventColor,
      ),
      title: Text('${event.event}${event.subReason != null ? ' — ${event.subReason}' : ''}'),
      subtitle: Text(event.action),
      trailing: Text(event.tsIst, style: const TextStyle(color: AppColors.textMuted, fontSize: 12)),
    );
  }
}

class _FullTraceView extends ConsumerWidget {
  const _FullTraceView({required this.runId, required this.date});

  final String runId;
  final String date;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = (runId: runId, date: date, full: true);
    final fullAsync = ref.watch(backtestDecisionsProvider(key));

    return Container(
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: AppColors.border))),
      child: fullAsync.when(
        data: (events) => ListView.builder(
          padding: const EdgeInsets.all(8),
          itemCount: events.length,
          itemBuilder: (context, i) {
            final e = events[i];
            return Text(
              '${e.tsIst}  ${e.event}${e.subReason != null ? '/${e.subReason}' : ''}  ${e.action}',
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            );
          },
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
      ),
    );
  }
}
