/// Positions tab — Kite-style execution monitor.
///
/// Layout (responsive):
///   Wide:  ┌─ index prices (full width) ───────────────────────────┐
///          │ POSITIONS (per-underlying)      │  INDICATOR PANEL     │
///          │  Open/Active table              │  (side split)        │
///          │  Closed table                   │                      │
///   Narrow: same, stacked (indicators below positions).
///
/// Open legs come from the live /monitor snapshot (entry · ltp · P&L · day-hi/lo ·
/// entry reason). Closed trades come from /strangle/trades (entry → exit · P&L ·
/// exit reason). System-placed legs only; manual broker positions live in the
/// Broker (Dhan) tab.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/widgets/pnl_text.dart';
import '../../application/manage_providers.dart';
import '../../domain/execution_models.dart';
import '../indicator_panel.dart';

const _indexOrder = ['NIFTY', 'BANKNIFTY', 'SENSEX'];

// Below this width the indicator panel stacks under the positions instead of
// docking to the right.
const _splitBreakpoint = 900.0;

class StrategyExecutionTab extends ConsumerWidget {
  const StrategyExecutionTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final monitorAsync = ref.watch(monitorStreamProvider);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(monitorStreamProvider),
      child: monitorAsync.when(
        data: (snap) => _PositionsBody(snap: snap),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _ErrorView(error: err, ref: ref),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final Object error;
  final WidgetRef ref;
  const _ErrorView({required this.error, required this.ref});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.signal_wifi_off, size: 48, color: Colors.orange),
          const SizedBox(height: 12),
          Text('Monitor unavailable', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text('Strategy may not be running',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => ref.invalidate(monitorStreamProvider),
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }
}

class _PositionsBody extends ConsumerWidget {
  final MonitorSnapshot snap;
  const _PositionsBody({required this.snap});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final todayStr = DateFormat('yyyy-MM-dd').format(DateTime.now());
    final tradesAsync = ref.watch(strangleTradesProvider(todayStr));
    final trades = tradesAsync.asData?.value;

    final indicators = IndicatorPanel(
      indicators: snap.indicators,
      atmCe: snap.atmCe,
      atmPe: snap.atmPe,
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= _splitBreakpoint;
        // The indicator panel's DataTable needs ~660px to show every column
        // (incl. the 3 SuperTrend variants + Camarilla) without its own
        // horizontal scroll. A fixed 440px clipped CamR4/CamS4 off-screen when
        // the window was maximized — give the panel a third of the available
        // width instead, clamped so it never starves the positions column on a
        // merely-wide (not maximized) window, nor over-shrinks on an ultrawide one.
        final panelWidth = (constraints.maxWidth * 0.32).clamp(440.0, 720.0);
        return Column(
          children: [
            _IndexPriceRow(indices: snap.indices),
            const Divider(height: 1),
            Expanded(
              child: wide
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          flex: 3,
                          child: _PositionsColumn(snap: snap, trades: trades),
                        ),
                        const VerticalDivider(width: 1),
                        SizedBox(width: panelWidth, child: indicators),
                      ],
                    )
                  : ListView(
                      padding: EdgeInsets.zero,
                      children: [
                        _PositionsColumn(snap: snap, trades: trades, nested: true),
                        const Divider(),
                        SizedBox(height: 360, child: indicators),
                      ],
                    ),
            ),
          ],
        );
      },
    );
  }
}

// ─── Left column: overall status + per-underlying open/closed ────────────────

class _PositionsColumn extends StatelessWidget {
  final MonitorSnapshot snap;
  final StrangleTrades? trades;

  /// Set when this sits inside the narrow layout's outer `ListView`, which
  /// supplies no height bound. Shrink-wrapping keeps the outer list the only
  /// scrollable; the section count is small so the cost is negligible.
  final bool nested;

  const _PositionsColumn({
    required this.snap,
    required this.trades,
    this.nested = false,
  });

  @override
  Widget build(BuildContext context) {
    final unders = <String>{
      ...snap.groups.map((g) => g.underlying),
      ...?trades?.byIndex.keys,
    }.toList()
      ..sort((a, b) {
        final ia = _indexOrder.indexOf(a);
        final ib = _indexOrder.indexOf(b);
        return (ia == -1 ? 99 : ia).compareTo(ib == -1 ? 99 : ib);
      });

    return ListView(
      shrinkWrap: nested,
      physics: nested ? const NeverScrollableScrollPhysics() : null,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      children: [
        _PremarketBanner(premarket: snap.premarket),
        _OverallStatusBar(snap: snap),
        const SizedBox(height: 6),
        _RecentEventsStrip(events: snap.recentEvents),
        const SizedBox(height: 8),
        if (unders.isEmpty)
          const _EmptyCard(message: 'No positions today')
        else
          ...unders.map((u) {
            final group = snap.groups.where((g) => g.underlying == u).firstOrNull;
            final rows = trades?.byIndex[u] ?? const [];
            return _UnderlyingSection(
              underlying: u,
              group: group,
              closed: rows.where((r) => !r.open).toList(),
            );
          }),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _OverallStatusBar extends StatelessWidget {
  final MonitorSnapshot snap;
  const _OverallStatusBar({required this.snap});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final bkt = snap.bucket ?? '--';
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            // Scrolls horizontally rather than overflowing on a narrow phone —
            // this cluster grows with score/readiness and Day P&L must stay visible.
            Flexible(
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    _BucketChip(bucket: bkt),
                    const SizedBox(width: 8),
                    if (snap.score != null)
                      Text('Score: ${snap.score!.toStringAsFixed(2)}',
                          style: Theme.of(context).textTheme.bodySmall),
                    const SizedBox(width: 8),
                    _ReadinessChip(readiness: snap.readiness),
                    const SizedBox(width: 8),
                    _FreshnessBadge(snap: snap),
                  ],
                ),
              ),
            ),
            const Spacer(),
            Text('Day P&L  ', style: Theme.of(context).textTheme.bodySmall),
            PnlText(snap.dayPnl,
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
            const SizedBox(width: 6),
            if (snap.doneForDay)
              Chip(
                label: const Text('DONE'),
                backgroundColor: cs.errorContainer,
                side: BorderSide.none,
              ),
          ],
        ),
      ),
    );
  }
}

// ─── Recent activity strip (incl. entry_aborted) ──────────────────────────────

/// Newest-first strip of strategy activity events (`recent_events` from the
/// monitor snapshot). Without this, an aborted entry (`entry_aborted` —
/// see `strangle-entry-fill-race-and-latch`) was only ever visible in the
/// backend log; the panel just showed "legs: []", indistinguishable from a
/// quiet, correctly-neutral day.
class _RecentEventsStrip extends StatelessWidget {
  final List<Map<String, dynamic>> events;
  const _RecentEventsStrip({required this.events});

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) return const SizedBox.shrink();
    final shown = events.take(5).toList();
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Recent activity',
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 2),
            ...shown.map((e) => _EventLine(event: e)),
          ],
        ),
      ),
    );
  }
}

class _EventLine extends StatelessWidget {
  final Map<String, dynamic> event;
  const _EventLine({required this.event});

  @override
  Widget build(BuildContext context) {
    final type = event['event_type'] as String? ?? '';
    final aborted = type == 'entry_aborted';
    final underlying = event['underlying'] as String?;
    final reason = event['reason'] as String?;
    final hhmm = _fmtTime(event['ist_time'] as String? ?? event['ts'] as String?);
    final typeLabel = type.isEmpty ? '' : type.replaceAll('_', ' ');

    final parts = <String>[
      if (underlying != null && underlying.isNotEmpty) underlying,
      typeLabel,
      if (reason != null && reason.isNotEmpty) '($reason)',
    ];
    final label = parts.join(' ');
    final color = aborted ? Colors.orange : Theme.of(context).colorScheme.onSurfaceVariant;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1.5),
      child: Row(
        children: [
          Icon(
            aborted ? Icons.warning_amber_rounded : Icons.circle,
            size: aborted ? 12 : 5,
            color: aborted ? Colors.orange : Colors.grey,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(label,
                style: TextStyle(
                    fontSize: 11,
                    color: color,
                    fontWeight: aborted ? FontWeight.w600 : FontWeight.normal),
                overflow: TextOverflow.ellipsis),
          ),
          if (hhmm != null)
            Text(hhmm, style: const TextStyle(fontSize: 10, color: Colors.grey)),
        ],
      ),
    );
  }

  String? _fmtTime(String? iso) {
    if (iso == null || iso.isEmpty) return null;
    final dt = DateTime.tryParse(iso);
    if (dt == null) return null;
    final local = dt.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }
}

// ─── Per-underlying: header + Open table + Closed table ──────────────────────

class _UnderlyingSection extends StatelessWidget {
  final String underlying;
  final UnderlyingGroup? group;
  final List<StrangleTradeRow> closed;

  const _UnderlyingSection({
    required this.underlying,
    required this.group,
    required this.closed,
  });

  @override
  Widget build(BuildContext context) {
    final openLegs = group?.legs ?? const [];
    final bkt = group?.bucket ?? '--';
    final dayPnl = group?.dayPnl ?? 0.0;
    final dayRealized = group?.dayRealized ?? 0.0;
    final dayUnrealized = group?.dayUnrealized ?? 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 4),
          child: Row(
            children: [
              Text(underlying,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(width: 8),
              _BucketChip(bucket: bkt),
              const Spacer(),
              // Combined per-underlying P&L (realized + unrealized), bold.
              PnlText(dayPnl,
                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
            ],
          ),
        ),
        // Breakdown line so the combined figure above is legible at a glance.
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text('realized ', style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).textTheme.bodySmall?.color?.withValues(alpha: 0.6),
                  )),
              PnlText(dayRealized, style: Theme.of(context).textTheme.bodySmall),
              Text('  ·  unrealized ', style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).textTheme.bodySmall?.color?.withValues(alpha: 0.6),
                  )),
              PnlText(dayUnrealized, style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
        _GroupLabel('Open / Active (${openLegs.length})'),
        if (openLegs.isEmpty)
          const _MutedLine('no open legs')
        else
          _OpenLegsTable(legs: openLegs),
        const SizedBox(height: 6),
        _GroupLabel('Closed today (${closed.length})'),
        if (closed.isEmpty)
          const _MutedLine('no closed trades')
        else
          _ClosedTradesTable(rows: closed),
        const SizedBox(height: 4),
        const Divider(),
      ],
    );
  }
}

class _OpenLegsTable extends StatelessWidget {
  final List<LegRow> legs;
  const _OpenLegsTable({required this.legs});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 46,
        columnSpacing: 12,
        columns: const [
          DataColumn(label: Text('Type')),
          DataColumn(label: Text('Strike'), numeric: true),
          DataColumn(label: Text('DTE'), numeric: true),
          DataColumn(label: Text('Lots'), numeric: true),
          DataColumn(label: Text('Entry'), numeric: true),
          DataColumn(label: Text('LTP'), numeric: true),
          DataColumn(label: Text('P&L'), numeric: true),
          DataColumn(label: Text('Day H'), numeric: true),
          DataColumn(label: Text('Day L'), numeric: true),
          DataColumn(label: Text('Entry reason')),
        ],
        rows: legs.map((leg) {
          final mtm = leg.mtm ?? 0;
          final tag = leg.isHedge ? 'H' : leg.isMomentum ? 'M' : leg.optType;
          final tagColor = leg.optType == 'CE' ? Colors.indigo : Colors.deepOrange;
          return DataRow(cells: [
            DataCell(_Tag(tag: tag, color: tagColor)),
            DataCell(Text(leg.strike.toStringAsFixed(0))),
            // DTE distinguishes a rehydrated multi-day-old leg from a same-day entry
            // even when entry_time is null (rehydrated legs have no timestamp).
            DataCell(Text(leg.dte != null ? '${leg.dte}' : '--')),
            DataCell(Text('${leg.lots}')),
            DataCell(Text(leg.entryPrice > 0 ? leg.entryPrice.toStringAsFixed(1) : '—')),
            DataCell(Text(leg.ltp != null ? leg.ltp!.toStringAsFixed(1) : '--')),
            DataCell(Text(
              leg.mtm != null ? leg.mtm!.toStringAsFixed(0) : '--',
              style: TextStyle(
                  color: mtm >= 0 ? AppColors.profit : AppColors.loss,
                  fontWeight: FontWeight.w600),
            )),
            DataCell(Text(leg.dayHigh != null ? leg.dayHigh!.toStringAsFixed(1) : '--')),
            DataCell(Text(leg.dayLow != null ? leg.dayLow!.toStringAsFixed(1) : '--')),
            DataCell(_ReasonNote(text: leg.entryReason)),
          ]);
        }).toList(),
      ),
    );
  }
}

class _ClosedTradesTable extends StatelessWidget {
  final List<StrangleTradeRow> rows;
  const _ClosedTradesTable({required this.rows});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 30,
        dataRowMinHeight: 32,
        dataRowMaxHeight: 46,
        columnSpacing: 12,
        columns: const [
          DataColumn(label: Text('Type')),
          DataColumn(label: Text('Strike'), numeric: true),
          DataColumn(label: Text('Lots'), numeric: true),
          DataColumn(label: Text('Entry'), numeric: true),
          DataColumn(label: Text('Exit'), numeric: true),
          DataColumn(label: Text('P&L'), numeric: true),
          DataColumn(label: Text('Exit reason')),
        ],
        rows: rows.map((r) {
          final pnl = r.pnl ?? 0;
          final tag = r.isHedge ? 'H' : (r.optType ?? '');
          final tagColor = r.optType == 'CE' ? Colors.indigo : Colors.deepOrange;
          return DataRow(cells: [
            DataCell(_Tag(tag: tag, color: tagColor)),
            DataCell(Text(r.strike?.toStringAsFixed(0) ?? '--')),
            DataCell(Text('${r.lots.toInt()}')),
            DataCell(Text(r.entryPrice?.toStringAsFixed(1) ?? '--')),
            DataCell(Text(r.exitPrice?.toStringAsFixed(1) ?? '--')),
            DataCell(PnlText(pnl,
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12))),
            DataCell(_ReasonNote(text: r.exitReason)),
          ]);
        }).toList(),
      ),
    );
  }
}

// ─── Small shared widgets ────────────────────────────────────────────────────

class _IndexPriceRow extends StatelessWidget {
  final List<IndexPrice> indices;
  const _IndexPriceRow({required this.indices});

  @override
  Widget build(BuildContext context) {
    final indexMap = {for (final i in indices) i.name: i};
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      child: Row(
        children: _indexOrder.map((name) {
          final price = indexMap[name];
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              // Three fixed-share cells: on a phone "BANKNIFTY 52100.00" is
              // wider than its third of the strip. Scale rather than ellipsize
              // so the index name stays readable.
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text('$name  ',
                        style: Theme.of(context)
                            .textTheme
                            .labelMedium
                            ?.copyWith(color: cs.primary)),
                    Text(
                      price != null ? price.spot.toStringAsFixed(2) : '--',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _BucketChip extends StatelessWidget {
  final String bucket;
  const _BucketChip({required this.bucket});

  @override
  Widget build(BuildContext context) {
    final color = _bucketColor(bucket);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(bucket,
          style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600)),
    );
  }
}

/// Strategy readiness gate (`ok`/`degraded`/`blocked`, composed from
/// Reconciliation/Broker Sync/Indicators/Chain/Bias components — see
/// `GET /api/v1/strangle/readiness` and `pdp/events/CLAUDE.md`).
///
/// `ok` renders nothing (unobtrusive); `degraded`/`blocked` render a chip whose
/// tooltip lists every non-ok component + reason, per-underlying.
class _ReadinessChip extends StatelessWidget {
  final MonitorReadiness readiness;
  const _ReadinessChip({required this.readiness});

  @override
  Widget build(BuildContext context) {
    if (readiness.state == 'ok') return const SizedBox.shrink();

    final blocked = readiness.state == 'blocked';
    final color = blocked ? AppColors.loss : Colors.amber;
    final label = blocked ? 'BLOCKED' : 'DEGRADED';

    final reasons = <String>[];
    for (final entry in readiness.byUnderlying.entries) {
      for (final c in entry.value.components) {
        if (c.state != 'ok') {
          reasons.add('${entry.key} · ${c.name}: ${c.reason ?? c.state}');
        }
      }
    }
    final tooltipMsg = reasons.isEmpty ? 'Readiness $label' : reasons.join('\n');

    return Tooltip(
      message: tooltipMsg,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: color.withValues(alpha: blocked ? 0.18 : 0.12),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: color.withValues(alpha: 0.6)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(blocked ? Icons.block : Icons.warning_amber_rounded, size: 12, color: color),
            const SizedBox(width: 3),
            Text(label,
                style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}

/// Prominent, non-dismissible banner shown when today's premarket warmup job
/// (`task warmup`) has not run. The trading process boots read-only and trades
/// intraday regardless — but the deep higher-timeframe history (EMA200, weekly
/// pivots) is only reconciled by that job, so those periods read `--` until it
/// runs. Renders nothing on the normal (ran) path. See the warmup-decouple directive.
class _PremarketBanner extends StatelessWidget {
  final PremarketStatus premarket;
  const _PremarketBanner({required this.premarket});

  @override
  Widget build(BuildContext context) {
    if (premarket.ranToday) return const SizedBox.shrink();
    const color = Colors.orange;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.6)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.warning_amber_rounded, size: 16, color: color),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'Premarket warmup not run today — higher-timeframe indicators '
                '(EMA200, weekly pivots) may show "--" until it runs. Run  '
                'task warmup  before/at market open to reconcile deep history. '
                'Intraday trading is unaffected.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: color,
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Data-freshness cue so a stuck poll or a dead feed reads as "stale", not as
/// silently-identical-to-live "--" cells. Combines two independent staleness
/// signals: how long ago the server actually built this payload (`as_of` —
/// catches a stuck client poll or a hung backend) and how long since the
/// primary index last ticked (`spot_age_s` — catches a dead market feed even
/// when the backend itself is polling fine). The worse of the two wins.
class _FreshnessBadge extends StatelessWidget {
  final MonitorSnapshot snap;
  const _FreshnessBadge({required this.snap});

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final payloadAgeS = snap.asOf != null
        ? now.difference(snap.asOf!).inSeconds.toDouble()
        : null;
    final spotAges = snap.indices.map((i) => i.spotAgeS).whereType<double>().toList();
    final noLiveTick = spotAges.isEmpty;
    final worstSpotAgeS = noLiveTick ? null : spotAges.reduce((a, b) => a > b ? a : b);

    double? effectiveAgeS;
    for (final v in [payloadAgeS, worstSpotAgeS]) {
      if (v == null) continue;
      if (effectiveAgeS == null || v > effectiveAgeS) effectiveAgeS = v;
    }

    // Redis LTP keys carry a 5s TTL and the panel polls every 2s — beyond ~10s
    // combined slack, the snapshot is genuinely stale, not just mid-poll.
    final stale = noLiveTick || (effectiveAgeS != null && effectiveAgeS > 10);
    final color = stale ? Colors.orange : AppColors.profit;
    final label = noLiveTick
        ? 'feed stale'
        : (effectiveAgeS != null ? '${effectiveAgeS.toStringAsFixed(0)}s ago' : 'no data');

    final tooltip = snap.asOf != null
        ? 'Snapshot built ${DateFormat('HH:mm:ss').format(snap.asOf!)}'
            '${noLiveTick ? '\nNo index tick in the last 5s' : ''}'
        : 'No server timestamp on this snapshot';

    return Tooltip(
      message: tooltip,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(stale ? Icons.wifi_off : Icons.wifi, size: 12, color: color),
          const SizedBox(width: 3),
          Text(label, style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  final String tag;
  final Color color;
  const _Tag({required this.tag, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(tag,
          style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11)),
    );
  }
}

class _ReasonNote extends StatelessWidget {
  final String? text;
  const _ReasonNote({required this.text});

  @override
  Widget build(BuildContext context) {
    final t = (text == null || text!.isEmpty) ? '--' : text!;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 160),
      child: Tooltip(
        message: t,
        child: Text(t,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 11)),
      ),
    );
  }
}

class _GroupLabel extends StatelessWidget {
  final String text;
  const _GroupLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: Text(text,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
    );
  }
}

class _MutedLine extends StatelessWidget {
  final String text;
  const _MutedLine(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 2),
      child: Text(text, style: const TextStyle(fontSize: 12, color: Colors.grey)),
    );
  }
}

class _EmptyCard extends StatelessWidget {
  final String message;
  const _EmptyCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Center(
            child: Text(message, style: Theme.of(context).textTheme.bodySmall)),
      ),
    );
  }
}

Color _bucketColor(String bucket) {
  switch (bucket.toLowerCase()) {
    case 'complete_bull':
    case 'most_bull':
      return Colors.green;
    case 'more_bull':
      return Colors.lightGreen;
    case 'complete_bear':
    case 'most_bear':
      return Colors.red;
    case 'more_bear':
      return Colors.orange;
    case 'neutral':
      return Colors.blueGrey;
    default:
      return Colors.grey;
  }
}
