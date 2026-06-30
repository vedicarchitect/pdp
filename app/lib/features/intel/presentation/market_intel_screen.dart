import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../application/intel_providers.dart';

class MarketIntelScreen extends StatelessWidget {
  const MarketIntelScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Market Intel'),
      ),
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Left Column (Commodities, Sentiment, Calendar)
          Expanded(
            flex: 2,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: const [
                _CommoditiesSection(),
                SizedBox(height: 24),
                _SentimentSection(),
                SizedBox(height: 24),
                _CalendarSection(),
              ],
            ),
          ),
          const VerticalDivider(width: 1),
          // Right Column (News)
          const Expanded(
            flex: 1,
            child: _NewsSection(),
          ),
        ],
      ),
    );
  }
}

class _CommoditiesSection extends ConsumerWidget {
  const _CommoditiesSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final commoditiesAsync = ref.watch(commoditiesProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Commodities', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        commoditiesAsync.when(
          data: (commodities) {
            return Row(
              children: commodities.map((c) {
                final isPositive = c.changePct >= 0;
                return Expanded(
                  child: Card(
                    margin: const EdgeInsets.only(right: 8),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(c.name, style: const TextStyle(fontWeight: FontWeight.bold)),
                          const SizedBox(height: 4),
                          Text('\$${c.price.toStringAsFixed(2)}', style: Theme.of(context).textTheme.titleMedium),
                          Text(
                            '${isPositive ? '+' : ''}${c.changePct}%',
                            style: TextStyle(
                              color: isPositive ? Colors.green : Colors.red,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }).toList(),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}

class _SentimentSection extends ConsumerWidget {
  const _SentimentSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sentimentAsync = ref.watch(sentimentProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Market Sentiment', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        sentimentAsync.when(
          data: (sentiment) {
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Stack(
                      alignment: Alignment.center,
                      children: [
                        SizedBox(
                          width: 100,
                          height: 100,
                          child: CircularProgressIndicator(
                            value: sentiment.overallScore / 100,
                            strokeWidth: 8,
                            backgroundColor: Colors.grey.withValues(alpha: 0.2),
                            color: sentiment.overallScore > 50 ? Colors.green : Colors.red,
                          ),
                        ),
                        Text(
                          '${sentiment.overallScore}',
                          style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
                        ),
                      ],
                    ),
                    const SizedBox(width: 32),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Overall: ${sentiment.label}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
                          const SizedBox(height: 12),
                          _SentimentBar(label: 'Positive', percentage: sentiment.positive, color: Colors.green),
                          _SentimentBar(label: 'Neutral', percentage: sentiment.neutral, color: Colors.grey),
                          _SentimentBar(label: 'Negative', percentage: sentiment.negative, color: Colors.red),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}

class _SentimentBar extends StatelessWidget {
  final String label;
  final int percentage;
  final Color color;

  const _SentimentBar({required this.label, required this.percentage, required this.color});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(width: 70, child: Text(label)),
          Expanded(
            child: LinearProgressIndicator(
              value: percentage / 100,
              backgroundColor: color.withValues(alpha: 0.2),
              color: color,
            ),
          ),
          const SizedBox(width: 8),
          Text('$percentage%'),
        ],
      ),
    );
  }
}

class _CalendarSection extends ConsumerWidget {
  const _CalendarSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final calendarAsync = ref.watch(calendarProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Economic Calendar', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        calendarAsync.when(
          data: (events) {
            return Card(
              child: ListView.separated(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: events.length,
                separatorBuilder: (context, index) => const Divider(height: 1),
                itemBuilder: (context, index) {
                  final event = events[index];
                  final isHighImpact = event.impact.toLowerCase() == 'high';

                  return ListTile(
                    leading: Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: isHighImpact ? Colors.red.withValues(alpha: 0.1) : Colors.orange.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(event.country, style: TextStyle(fontWeight: FontWeight.bold, color: isHighImpact ? Colors.red : Colors.orange)),
                    ),
                    title: Text(event.event, style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text(DateFormat('MMM dd, HH:mm').format(event.time)),
                    trailing: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text('Fcst: ${event.forecast ?? '-'}'),
                        Text('Prev: ${event.previous ?? '-'}'),
                      ],
                    ),
                  );
                },
              ),
            );
          },
          loading: () => const CircularProgressIndicator(),
          error: (err, _) => Text('Error: $err'),
        ),
      ],
    );
  }
}

class _NewsSection extends ConsumerWidget {
  const _NewsSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final newsAsync = ref.watch(newsProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text('Trending News', style: Theme.of(context).textTheme.titleLarge),
        ),
        Expanded(
          child: newsAsync.when(
            data: (articles) {
              return ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: articles.length,
                separatorBuilder: (context, index) => const Divider(),
                itemBuilder: (context, index) {
                  final article = articles[index];
                  final isPositive = article.sentiment == 'positive';

                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              article.source,
                              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).colorScheme.primary),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              DateFormat('HH:mm').format(article.publishedAt),
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            const Spacer(),
                            Icon(
                              isPositive ? Icons.trending_up : Icons.trending_down,
                              color: isPositive ? Colors.green : Colors.red,
                              size: 16,
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          article.headline,
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                        ),
                      ],
                    ),
                  );
                },
              );
            },
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (err, _) => Center(child: Text('Error: $err')),
          ),
        ),
      ],
    );
  }
}
