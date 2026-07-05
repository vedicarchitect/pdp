import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/theme/app_colors.dart';
import '../../application/backtest_providers.dart';
import '../../domain/coverage.dart';

const _underlyings = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

const _familyTask = {
  'spot': 'backfill-spot',
  'options': 'backfill-options',
  'vix': 'backfill-vix',
  'levels_daily': 'backfill-levels',
  'levels_weekly': 'backfill-levels',
};

const _familyLabel = {
  'spot': 'Spot / VWAP',
  'options': 'Options chain',
  'vix': 'VIX',
  'levels_daily': 'Camarilla (daily)',
  'levels_weekly': 'Camarilla (weekly)',
  'futures': 'Futures',
};

/// Data coverage + gap radar: per-index/family coverage with one-click
/// backfill buttons whose job progress streams live.
class CoverageTab extends ConsumerWidget {
  const CoverageTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(coverageUnderlyingProvider);
    final coverageAsync = ref.watch(coverageProvider);

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              DropdownButton<String?>(
                value: selected,
                hint: const Text('All indices'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('All indices')),
                  ..._underlyings.map((u) => DropdownMenuItem(value: u, child: Text(u))),
                ],
                onChanged: (v) => ref.read(coverageUnderlyingProvider.notifier).state = v,
              ),
              const Spacer(),
              IconButton(icon: const Icon(Icons.refresh), onPressed: () => ref.invalidate(coverageProvider)),
            ],
          ),
        ),
        Expanded(
          child: coverageAsync.when(
            data: (coverage) => ListView(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: coverage.underlyings.values
                  .map((u) => _UnderlyingCoverageCard(coverage: u))
                  .toList(growable: false),
            ),
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, _) => Center(child: Text('Error: $err', style: const TextStyle(color: AppColors.loss))),
          ),
        ),
      ],
    );
  }
}

class _UnderlyingCoverageCard extends StatelessWidget {
  const _UnderlyingCoverageCard({required this.coverage});

  final UnderlyingCoverage coverage;

  @override
  Widget build(BuildContext context) {
    final gapped = coverage.gappedDates;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(coverage.underlying, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            ...coverage.families.entries.map(
              (e) => _FamilyRow(underlying: coverage.underlying, family: e.key, coverage: e.value),
            ),
            if (gapped.isNotEmpty) ...[
              const Divider(height: 24),
              Text('Gap radar (${gapped.length} flagged day${gapped.length == 1 ? '' : 's'})',
                  style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: const [
                    DataColumn(label: Text('Date')),
                    DataColumn(label: Text('Spot')),
                    DataColumn(label: Text('Options')),
                    DataColumn(label: Text('VIX')),
                    DataColumn(label: Text('Weekly levels')),
                    DataColumn(label: Text('Futures')),
                  ],
                  rows: gapped.map((date) {
                    final statuses = coverage.radar[date]!;
                    Widget cell(String key) {
                      final s = statuses[key] ?? 'ready';
                      final ok = s == 'ready';
                      return Text(s, style: TextStyle(color: ok ? AppColors.profit : AppColors.warning));
                    }

                    return DataRow(cells: [
                      DataCell(Text(date)),
                      DataCell(cell('spot')),
                      DataCell(cell('options')),
                      DataCell(cell('vix')),
                      DataCell(cell('levels_weekly')),
                      DataCell(cell('futures')),
                    ]);
                  }).toList(growable: false),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _FamilyRow extends ConsumerStatefulWidget {
  const _FamilyRow({required this.underlying, required this.family, required this.coverage});

  final String underlying;
  final String family;
  final FamilyCoverage coverage;

  @override
  ConsumerState<_FamilyRow> createState() => _FamilyRowState();
}

class _FamilyRowState extends ConsumerState<_FamilyRow> {
  String? _jobId;

  Future<void> _backfill() async {
    final taskName = _familyTask[widget.family];
    if (taskName == null) return;
    final gap = widget.coverage.gapRanges.isNotEmpty ? widget.coverage.gapRanges.first : null;
    final jobId = await ref.read(backtestSourceProvider).runHousekeeping(taskName, {
      'underlying': widget.underlying,
      if (gap != null) 'date_from': gap[0],
      if (gap != null) 'date_to': gap[1],
    });
    setState(() => _jobId = jobId);
  }

  @override
  Widget build(BuildContext context) {
    final label = _familyLabel[widget.family] ?? widget.family;
    final c = widget.coverage;
    final hasGap = !c.isUnavailable && c.gapRanges.isNotEmpty;
    final canBackfill = _familyTask.containsKey(widget.family);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(width: 140, child: Text(label)),
          Expanded(
            child: c.isUnavailable
                ? Text(c.note ?? 'unavailable', style: const TextStyle(color: AppColors.neutral))
                : Text('${c.coveragePct.toStringAsFixed(1)}% (${c.coveredDays}/${c.totalDays} days)'),
          ),
          if (hasGap && _jobId == null)
            TextButton.icon(
              onPressed: canBackfill ? _backfill : null,
              icon: const Icon(Icons.build, size: 16),
              label: const Text('Backfill'),
            )
          else if (_jobId != null)
            SizedBox(
              width: 160,
              child: _BackfillProgress(
                jobId: _jobId!,
                onDone: () {
                  ref.invalidate(coverageProvider);
                  setState(() => _jobId = null);
                },
              ),
            )
          else
            const Icon(Icons.check_circle, color: AppColors.profit, size: 18),
        ],
      ),
    );
  }
}

class _BackfillProgress extends ConsumerWidget {
  const _BackfillProgress({required this.jobId, required this.onDone});

  final String jobId;
  final VoidCallback onDone;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final progressAsync = ref.watch(jobProgressProvider(jobId));
    return progressAsync.when(
      data: (p) {
        if (p.isTerminal) {
          Future.microtask(onDone);
        }
        return LinearProgressIndicator(value: p.progress / 100);
      },
      loading: () => const LinearProgressIndicator(),
      error: (_, __) => const Icon(Icons.error, color: AppColors.loss, size: 18),
    );
  }
}
