import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../shared/format.dart';
import '../../../shared/widgets/pnl_text.dart';
import '../../../shared/widgets/stat_card.dart';
import '../application/dashboard_providers.dart';
import '../domain/dashboard_models.dart';
import '../../events/presentation/critical_alerts_card.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stream = ref.watch(dashboardStreamProvider);

    return stream.when(
      data: (data) => _buildDashboard(context, ref, data),
      error: (e, st) => Center(child: Text('Error: $e', style: const TextStyle(color: AppColors.loss))),
      loading: () => const Center(child: CircularProgressIndicator()),
    );
  }

  Widget _buildDashboard(BuildContext context, WidgetRef ref, DashboardData data) {
    return CustomScrollView(
      slivers: [
        const CriticalAlertsCard(),
        SliverToBoxAdapter(
          child: SizedBox(
            height: 156,
            child: ListView.builder(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              itemCount: data.indices.length,
              itemBuilder: (context, i) => _MarketIndexCard(index: data.indices[i]),
            ),
          ),
        ),
        SliverPadding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          sliver: SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _GlobalMarketsStrip(data: data),
                const SizedBox(height: 24),
                _CommoditiesStrip(commodities: data.commodities),
                const SizedBox(height: 24),
                const _SectionTitle('Portfolio Snapshot'),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: StatCard(
                        label: 'Day P&L',
                        child: PnlText(data.summary.dayPnl, style: const TextStyle(fontSize: 24), showSign: true),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: StatCard(
                        label: 'Open Positions',
                        child: Text(
                          '${data.summary.openPositions}',
                          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600, color: AppColors.textPrimary),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: StatCard(
                        label: 'Unrealized P&L',
                        child: PnlText(data.summary.totalUnrealizedPnl, style: const TextStyle(fontSize: 18)),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: StatCard(
                        label: 'Realized P&L',
                        child: PnlText(data.summary.totalRealizedPnl, style: const TextStyle(fontSize: 18)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(child: _TodayPnlCard(todayPnl: data.todayPnl)),
                    const SizedBox(width: 16),
                    Expanded(child: _MarginCard(margin: data.margin)),
                  ],
                ),
                const SizedBox(height: 16),
                _VixCard(vix: data.vix),
                const SizedBox(height: 24),
                _StrategyChipsRow(strategies: data.strategies),
                const SizedBox(height: 24),
                _FiiDiiPanel(fiiDii: data.fiiDii),
                const SizedBox(height: 24),
                _SentimentPanel(sentiment: data.sentiment, news: data.news),
                const SizedBox(height: 24),
                _NextExpiryChips(nextExpiry: data.nextExpiry),
                const SizedBox(height: 24),
                _WatchlistSection(data: data),
                const SizedBox(height: 32),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Text(
        text,
        style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AppColors.textPrimary),
      );
}

class _MarketIndexCard extends StatelessWidget {
  const _MarketIndexCard({required this.index});

  final MarketIndex index;

  @override
  Widget build(BuildContext context) {
    if (!index.available) {
      return _UnavailableCard(label: index.name);
    }
    final color = index.isUp ? AppColors.profit : AppColors.loss;
    final icon = index.isUp ? Icons.arrow_upward : Icons.arrow_downward;

    return Container(
      width: 160,
      margin: const EdgeInsets.only(right: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            index.name,
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textMuted),
          ),
          Expanded(child: _IndexSparkline(values: index.sparkline, color: color)),
          Text(
            formatInr(index.ltp),
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: AppColors.textPrimary),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(icon, size: 14, color: color),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  '${index.change > 0 ? "+" : ""}${index.change.toStringAsFixed(1)} (${index.changePct.toStringAsFixed(2)}%)',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color),
                  overflow: TextOverflow.ellipsis,
                  maxLines: 1,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// A minimal trend sparkline for an index card, drawn from a client-tracked
/// rolling window of recent ticks — empty until enough ticks have arrived.
class _IndexSparkline extends StatelessWidget {
  const _IndexSparkline({required this.values, required this.color});

  final List<double> values;
  final Color color;

  @override
  Widget build(BuildContext context) {
    if (values.length < 2) return const SizedBox.shrink();

    var minY = values.reduce((a, b) => a < b ? a : b);
    var maxY = values.reduce((a, b) => a > b ? a : b);
    if (minY == maxY) {
      minY -= 1;
      maxY += 1;
    }

    return LineChart(
      LineChartData(
        gridData: const FlGridData(show: false),
        titlesData: const FlTitlesData(show: false),
        borderData: FlBorderData(show: false),
        lineTouchData: const LineTouchData(enabled: false),
        minY: minY,
        maxY: maxY,
        lineBarsData: [
          LineChartBarData(
            spots: [for (var i = 0; i < values.length; i++) FlSpot(i.toDouble(), values[i])],
            isCurved: true,
            color: color,
            barWidth: 1.5,
            dotData: const FlDotData(show: false),
          ),
        ],
      ),
    );
  }
}

class _UnavailableCard extends StatelessWidget {
  const _UnavailableCard({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 160,
      margin: const EdgeInsets.only(right: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textMuted)),
          const Spacer(),
          const Text('Unavailable', style: TextStyle(fontSize: 13, color: AppColors.neutral)),
        ],
      ),
    );
  }
}

class _GlobalMarketsStrip extends StatelessWidget {
  const _GlobalMarketsStrip({required this.data});
  final DashboardData data;

  @override
  Widget build(BuildContext context) {
    if (!data.globalIndicesAvailable || data.globalIndices.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Global Markets'),
        const SizedBox(height: 12),
        SizedBox(
          height: 64,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: data.globalIndices.length,
            separatorBuilder: (_, __) => const SizedBox(width: 12),
            itemBuilder: (context, i) {
              final q = data.globalIndices[i];
              final color = q.isUp ? AppColors.profit : AppColors.loss;
              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.surfaceAlt,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(q.symbol, style: const TextStyle(fontSize: 11, color: AppColors.textMuted, fontWeight: FontWeight.w600)),
                    Text(
                      '${q.close.toStringAsFixed(1)}  ${q.changePct >= 0 ? "+" : ""}${q.changePct.toStringAsFixed(2)}%',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: color),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _CommoditiesStrip extends StatelessWidget {
  const _CommoditiesStrip({required this.commodities});
  final List<CommodityQuote> commodities;

  @override
  Widget build(BuildContext context) {
    if (commodities.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Commodities (MCX)'),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: commodities.map((c) {
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: AppColors.surfaceAlt,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(c.name, style: const TextStyle(fontSize: 11, color: AppColors.textMuted, fontWeight: FontWeight.w600)),
                  Text(
                    c.available ? formatInr(c.ltp, showSign: false) : 'Unavailable',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: c.available ? AppColors.textPrimary : AppColors.neutral,
                    ),
                  ),
                ],
              ),
            );
          }).toList(),
        ),
      ],
    );
  }
}

class _VixCard extends StatelessWidget {
  const _VixCard({required this.vix});
  final VixData vix;

  @override
  Widget build(BuildContext context) {
    return StatCard(
      label: 'India VIX',
      child: Text(
        vix.available ? vix.value.toStringAsFixed(2) : 'Unavailable',
        style: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          color: vix.available ? AppColors.textPrimary : AppColors.neutral,
        ),
      ),
    );
  }
}

class _TodayPnlCard extends StatelessWidget {
  const _TodayPnlCard({required this.todayPnl});
  final TodayPnl todayPnl;

  @override
  Widget build(BuildContext context) {
    return StatCard(
      label: "Today's Realized P&L",
      child: todayPnl.available
          ? PnlText(todayPnl.realizedPnl, style: const TextStyle(fontSize: 18))
          : const Text('Unavailable', style: TextStyle(fontSize: 14, color: AppColors.neutral)),
    );
  }
}

class _MarginCard extends StatelessWidget {
  const _MarginCard({required this.margin});
  final MarginSnapshot margin;

  @override
  Widget build(BuildContext context) {
    return StatCard(
      label: 'Margin Available',
      child: margin.available
          ? Text(formatInr(margin.availableBalance, showSign: false), style: const TextStyle(fontSize: 18, color: AppColors.textPrimary))
          : const Text('Unavailable', style: TextStyle(fontSize: 14, color: AppColors.neutral)),
    );
  }
}

class _StrategyChipsRow extends StatelessWidget {
  const _StrategyChipsRow({required this.strategies});
  final StrategyChips strategies;

  @override
  Widget build(BuildContext context) {
    if (!strategies.available || strategies.strategies.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Strategies'),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: strategies.strategies.map((s) {
            final running = s.status == 'RUNNING';
            final color = running ? AppColors.profit : AppColors.neutral;
            return Chip(
              backgroundColor: AppColors.surfaceAlt,
              side: BorderSide(color: color),
              label: Text('${s.underlying} · ${s.status}', style: TextStyle(color: color, fontSize: 12)),
            );
          }).toList(),
        ),
      ],
    );
  }
}

class _FiiDiiPanel extends StatelessWidget {
  const _FiiDiiPanel({required this.fiiDii});
  final FiiDiiHistory fiiDii;

  @override
  Widget build(BuildContext context) {
    if (!fiiDii.available || fiiDii.days.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('FII / DII Net Flow'),
        const SizedBox(height: 12),
        ...fiiDii.days.map((d) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(d.date, style: const TextStyle(color: AppColors.textMuted, fontSize: 13)),
                  Row(
                    children: [
                      const Text('FII ', style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
                      PnlText(d.fiiNet, style: const TextStyle(fontSize: 13)),
                      const SizedBox(width: 16),
                      const Text('DII ', style: TextStyle(color: AppColors.textMuted, fontSize: 12)),
                      PnlText(d.diiNet, style: const TextStyle(fontSize: 13)),
                    ],
                  ),
                ],
              ),
            )),
      ],
    );
  }
}

class _SentimentPanel extends StatelessWidget {
  const _SentimentPanel({required this.sentiment, required this.news});
  final SentimentData sentiment;
  final NewsFeed news;

  @override
  Widget build(BuildContext context) {
    if (!sentiment.available && !news.available) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Sentiment & News'),
        const SizedBox(height: 12),
        if (sentiment.available)
          StatCard(
            label: 'Sentiment (${sentiment.label})',
            child: Text(
              sentiment.blendedScore.toStringAsFixed(0),
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: AppColors.textPrimary),
            ),
          ),
        if (news.available) ...[
          const SizedBox(height: 12),
          ...news.articles.take(5).map((a) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text(
                  '${a.headline}  —  ${a.source}',
                  style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
                ),
              )),
        ],
      ],
    );
  }
}

class _NextExpiryChips extends StatelessWidget {
  const _NextExpiryChips({required this.nextExpiry});
  final NextExpiry nextExpiry;

  @override
  Widget build(BuildContext context) {
    if (!nextExpiry.available) return const SizedBox.shrink();
    final entries = nextExpiry.expiries.entries.where((e) => e.value != null).toList();
    if (entries.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Next Expiry'),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: entries
              .map((e) => Chip(
                    backgroundColor: AppColors.surfaceAlt,
                    label: Text('${e.key}: ${e.value}', style: const TextStyle(color: AppColors.textPrimary, fontSize: 12)),
                  ))
              .toList(),
        ),
      ],
    );
  }
}

/// Resolves a live quote for a watchlist symbol from the same index/commodity
/// LTP data the rest of the dashboard already shows — returns null (no
/// fabricated value) when the symbol isn't one of those priced instruments.
String? _resolveWatchlistQuote(String symbol, DashboardData data) {
  for (final idx in data.indices) {
    if (idx.available && idx.name.toUpperCase() == symbol) {
      return formatInr(idx.ltp, showSign: false);
    }
  }
  for (final c in data.commodities) {
    if (c.available && c.symbol.toUpperCase() == symbol) {
      return formatInr(c.ltp, showSign: false);
    }
  }
  return null;
}

class _WatchlistSection extends ConsumerStatefulWidget {
  const _WatchlistSection({required this.data});

  final DashboardData data;

  @override
  ConsumerState<_WatchlistSection> createState() => _WatchlistSectionState();
}

class _WatchlistSectionState extends ConsumerState<_WatchlistSection> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final watchlist = ref.watch(watchlistProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionTitle('Watchlist'),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                style: const TextStyle(color: AppColors.textPrimary),
                decoration: const InputDecoration(
                  hintText: 'Add symbol (e.g. NIFTY)',
                  hintStyle: TextStyle(color: AppColors.textMuted),
                  isDense: true,
                ),
                onSubmitted: (v) {
                  ref.read(watchlistProvider.notifier).add(v);
                  _controller.clear();
                },
              ),
            ),
            IconButton(
              icon: const Icon(Icons.add, color: AppColors.info),
              onPressed: () {
                ref.read(watchlistProvider.notifier).add(_controller.text);
                _controller.clear();
              },
            ),
          ],
        ),
        const SizedBox(height: 8),
        watchlist.when(
          data: (symbols) => Wrap(
            spacing: 8,
            runSpacing: 8,
            children: symbols.map((s) {
              final quote = _resolveWatchlistQuote(s, widget.data);
              return Chip(
                backgroundColor: AppColors.surfaceAlt,
                label: Text(
                  quote != null ? '$s  $quote' : s,
                  style: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
                ),
                onDeleted: () => ref.read(watchlistProvider.notifier).remove(s),
                deleteIconColor: AppColors.textMuted,
              );
            }).toList(),
          ),
          error: (e, st) => const Text('Failed to load watchlist', style: TextStyle(color: AppColors.loss)),
          loading: () => const SizedBox(height: 24, width: 24, child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      ],
    );
  }
}
