class NewsArticle {
  final String id;
  final String headline;
  final String source;
  final String url;
  final DateTime publishedAt;
  final String sentiment;

  const NewsArticle({
    required this.id,
    required this.headline,
    required this.source,
    required this.url,
    required this.publishedAt,
    required this.sentiment,
  });

  factory NewsArticle.fromJson(Map<String, dynamic> json) {
    return NewsArticle(
      id: json['id'] as String,
      headline: json['headline'] as String,
      source: json['source'] as String,
      url: json['url'] as String,
      publishedAt: DateTime.parse(json['published_at'] as String),
      sentiment: json['sentiment'] as String,
    );
  }
}

class SentimentScore {
  final int overallScore;
  final String label;
  final int positive;
  final int neutral;
  final int negative;

  const SentimentScore({
    required this.overallScore,
    required this.label,
    required this.positive,
    required this.neutral,
    required this.negative,
  });

  factory SentimentScore.fromJson(Map<String, dynamic> json) {
    return SentimentScore(
      overallScore: json['overall_score'] as int,
      label: json['label'] as String,
      positive: json['breakdown']['positive'] as int,
      neutral: json['breakdown']['neutral'] as int,
      negative: json['breakdown']['negative'] as int,
    );
  }
}

class CommodityPrice {
  final String symbol;
  final String name;
  final double price;
  final double changePct;

  const CommodityPrice({
    required this.symbol,
    required this.name,
    required this.price,
    required this.changePct,
  });

  factory CommodityPrice.fromJson(Map<String, dynamic> json) {
    return CommodityPrice(
      symbol: json['symbol'] as String,
      name: json['name'] as String,
      price: (json['price'] as num).toDouble(),
      changePct: (json['change_pct'] as num).toDouble(),
    );
  }
}

class EconomicEvent {
  final String id;
  final String event;
  final String country;
  final String impact;
  final DateTime time;
  final String? actual;
  final String? forecast;
  final String? previous;

  const EconomicEvent({
    required this.id,
    required this.event,
    required this.country,
    required this.impact,
    required this.time,
    this.actual,
    this.forecast,
    this.previous,
  });

  factory EconomicEvent.fromJson(Map<String, dynamic> json) {
    return EconomicEvent(
      id: json['id'] as String,
      event: json['event'] as String,
      country: json['country'] as String,
      impact: json['impact'] as String,
      time: DateTime.parse(json['time'] as String),
      actual: json['actual'] as String?,
      forecast: json['forecast'] as String?,
      previous: json['previous'] as String?,
    );
  }
}
