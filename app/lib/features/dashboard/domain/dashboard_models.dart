import '../../portfolio/domain/portfolio_summary.dart';

double? _asDouble(dynamic v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

/// One tracked index (NIFTY/BANKNIFTY/SENSEX). `change`/`changePct` are always
/// computed against [prevClose] — never a running intraday sum.
class MarketIndex {
  const MarketIndex({
    required this.securityId,
    required this.name,
    required this.available,
    this.ltp = 0.0,
    this.prevClose,
    this.sparkline = const [],
  });

  final String securityId;
  final String name;
  final bool available;
  final double ltp;
  final double? prevClose;

  /// Rolling window of recent ticks for the mini trend chart — populated
  /// client-side as ticks arrive, not persisted server-side.
  final List<double> sparkline;

  double get change => (available && prevClose != null && prevClose != 0) ? ltp - prevClose! : 0.0;
  double get changePct =>
      (available && prevClose != null && prevClose != 0) ? (ltp - prevClose!) / prevClose! * 100 : 0.0;
  bool get isUp => change >= 0;

  factory MarketIndex.fromJson(String securityId, String name, Map<String, dynamic> json) {
    final available = json['available'] == true;
    return MarketIndex(
      securityId: securityId,
      name: name,
      available: available,
      ltp: _asDouble(json['ltp']) ?? 0.0,
      prevClose: _asDouble(json['prev_close']),
    );
  }

  MarketIndex copyWith({double? ltp, bool? available, List<double>? sparkline}) => MarketIndex(
        securityId: securityId,
        name: name,
        available: available ?? this.available,
        sparkline: sparkline ?? this.sparkline,
        ltp: ltp ?? this.ltp,
        prevClose: prevClose,
      );
}

class GlobalIndexQuote {
  const GlobalIndexQuote({
    required this.symbol,
    required this.close,
    required this.change,
    required this.changePct,
  });

  final String symbol;
  final double close;
  final double change;
  final double changePct;

  bool get isUp => change >= 0;

  factory GlobalIndexQuote.fromJson(Map<String, dynamic> json) => GlobalIndexQuote(
        symbol: json['symbol']?.toString() ?? '',
        close: _asDouble(json['close']) ?? 0.0,
        change: _asDouble(json['change']) ?? 0.0,
        changePct: _asDouble(json['change_pct']) ?? 0.0,
      );
}

class CommodityQuote {
  const CommodityQuote({
    required this.symbol,
    required this.name,
    required this.available,
    this.securityId,
    this.ltp = 0.0,
  });

  final String symbol;
  final String name;
  final bool available;
  final String? securityId;
  final double ltp;

  factory CommodityQuote.fromJson(Map<String, dynamic> json) => CommodityQuote(
        symbol: json['symbol']?.toString() ?? '',
        name: json['name']?.toString() ?? '',
        available: json['available'] == true,
        securityId: json['security_id']?.toString(),
        ltp: _asDouble(json['ltp']) ?? 0.0,
      );

  CommodityQuote copyWith({double? ltp, bool? available}) => CommodityQuote(
        symbol: symbol,
        name: name,
        available: available ?? this.available,
        securityId: securityId,
        ltp: ltp ?? this.ltp,
      );
}

class VixData {
  const VixData({required this.available, this.securityId, this.value = 0.0});

  final bool available;
  final String? securityId;
  final double value;

  factory VixData.fromJson(Map<String, dynamic> json) => VixData(
        available: json['available'] == true,
        securityId: json['security_id']?.toString(),
        value: _asDouble(json['value']) ?? 0.0,
      );

  static const empty = VixData(available: false);
}

class NextExpiry {
  const NextExpiry({required this.available, this.expiries = const {}});

  final bool available;
  final Map<String, String?> expiries;

  factory NextExpiry.fromJson(Map<String, dynamic> json) {
    final raw = json['expiries'] as Map<String, dynamic>? ?? {};
    return NextExpiry(
      available: json['available'] == true,
      expiries: raw.map((k, v) => MapEntry(k, v?.toString())),
    );
  }

  static const empty = NextExpiry(available: false);
}

class FiiDiiDay {
  const FiiDiiDay({required this.date, required this.fiiNet, required this.diiNet});

  final String date;
  final double fiiNet;
  final double diiNet;

  factory FiiDiiDay.fromJson(Map<String, dynamic> json) {
    final fii = (_asDouble(json['fii_index_futures_net']) ?? 0.0) +
        (_asDouble(json['fii_index_options_net']) ?? 0.0) +
        (_asDouble(json['fii_stock_futures_net']) ?? 0.0);
    final dii = (_asDouble(json['dii_index_futures_net']) ?? 0.0) +
        (_asDouble(json['dii_index_options_net']) ?? 0.0) +
        (_asDouble(json['dii_stock_futures_net']) ?? 0.0);
    return FiiDiiDay(date: json['date']?.toString() ?? '', fiiNet: fii, diiNet: dii);
  }
}

class FiiDiiHistory {
  const FiiDiiHistory({required this.available, this.days = const []});

  final bool available;
  final List<FiiDiiDay> days;

  factory FiiDiiHistory.fromJson(Map<String, dynamic> json) {
    final rawDays = json['days'] as List<dynamic>? ?? [];
    return FiiDiiHistory(
      available: json['available'] == true,
      days: rawDays.map((d) => FiiDiiDay.fromJson(d as Map<String, dynamic>)).toList(),
    );
  }

  static const empty = FiiDiiHistory(available: false);
}

class NewsArticle {
  const NewsArticle({required this.headline, required this.source, required this.url});

  final String headline;
  final String source;
  final String url;

  factory NewsArticle.fromJson(Map<String, dynamic> json) => NewsArticle(
        headline: json['headline']?.toString() ?? '',
        source: json['source']?.toString() ?? '',
        url: json['url']?.toString() ?? '',
      );
}

class NewsFeed {
  const NewsFeed({required this.available, this.articles = const []});

  final bool available;
  final List<NewsArticle> articles;

  factory NewsFeed.fromJson(Map<String, dynamic> json) {
    final raw = json['articles'] as List<dynamic>? ?? [];
    return NewsFeed(
      available: json['available'] == true,
      articles: raw.map((a) => NewsArticle.fromJson(a as Map<String, dynamic>)).toList(),
    );
  }

  static const empty = NewsFeed(available: false);
}

class SentimentData {
  const SentimentData({
    required this.available,
    this.blendedScore = 50.0,
    this.label = 'Neutral',
    this.newsScore,
    this.internalsScore,
  });

  final bool available;
  final double blendedScore;
  final String label;
  final double? newsScore;
  final double? internalsScore;

  factory SentimentData.fromJson(Map<String, dynamic> json) => SentimentData(
        available: json['available'] == true,
        blendedScore: _asDouble(json['blended_score']) ?? 50.0,
        label: json['label']?.toString() ?? 'Neutral',
        newsScore: _asDouble(json['news_score']),
        internalsScore: _asDouble(json['internals_score']),
      );

  static const empty = SentimentData(available: false);
}

class TodayPnl {
  const TodayPnl({required this.available, this.realizedPnl = 0.0, this.roundTrips = 0, this.winRate = 0.0});

  final bool available;
  final double realizedPnl;
  final int roundTrips;
  final double winRate;

  factory TodayPnl.fromJson(Map<String, dynamic> json) {
    final stats = json['stats'] as Map<String, dynamic>? ?? {};
    return TodayPnl(
      available: json['available'] == true,
      realizedPnl: _asDouble(stats['realized_pnl']) ?? 0.0,
      roundTrips: (stats['round_trips'] as num?)?.toInt() ?? 0,
      winRate: _asDouble(stats['win_rate']) ?? 0.0,
    );
  }

  static const empty = TodayPnl(available: false);
}

class MarginSnapshot {
  const MarginSnapshot({required this.available, this.availableBalance = 0.0, this.utilizedAmount = 0.0});

  final bool available;
  final double availableBalance;
  final double utilizedAmount;

  factory MarginSnapshot.fromJson(Map<String, dynamic> json) => MarginSnapshot(
        available: json['available'] == true,
        availableBalance: double.tryParse(json['available_balance']?.toString() ?? '') ?? 0.0,
        utilizedAmount: double.tryParse(json['utilized_amount']?.toString() ?? '') ?? 0.0,
      );

  static const empty = MarginSnapshot(available: false);
}

class StrategyChip {
  const StrategyChip({required this.id, required this.underlying, required this.status});

  final String id;
  final String underlying;
  final String status;

  factory StrategyChip.fromJson(Map<String, dynamic> json) => StrategyChip(
        id: json['id']?.toString() ?? '',
        underlying: json['underlying']?.toString() ?? '',
        status: json['status']?.toString() ?? '',
      );
}

class StrategyChips {
  const StrategyChips({required this.available, this.strategies = const []});

  final bool available;
  final List<StrategyChip> strategies;

  factory StrategyChips.fromJson(Map<String, dynamic> json) {
    final raw = json['strategies'] as List<dynamic>? ?? [];
    return StrategyChips(
      available: json['available'] == true,
      strategies: raw.map((s) => StrategyChip.fromJson(s as Map<String, dynamic>)).toList(),
    );
  }

  static const empty = StrategyChips(available: false);
}

/// Full dashboard snapshot — every section carries its own availability so the
/// UI can degrade honestly per-section instead of failing the whole screen.
class DashboardData {
  const DashboardData({
    required this.indices,
    required this.summary,
    this.globalIndices = const [],
    this.globalIndicesAvailable = false,
    this.commodities = const [],
    this.vix = VixData.empty,
    this.nextExpiry = NextExpiry.empty,
    this.fiiDii = FiiDiiHistory.empty,
    this.news = NewsFeed.empty,
    this.sentiment = SentimentData.empty,
    this.todayPnl = TodayPnl.empty,
    this.margin = MarginSnapshot.empty,
    this.strategies = StrategyChips.empty,
  });

  final List<MarketIndex> indices;
  final PortfolioSummary summary;
  final List<GlobalIndexQuote> globalIndices;
  final bool globalIndicesAvailable;
  final List<CommodityQuote> commodities;
  final VixData vix;
  final NextExpiry nextExpiry;
  final FiiDiiHistory fiiDii;
  final NewsFeed news;
  final SentimentData sentiment;
  final TodayPnl todayPnl;
  final MarginSnapshot margin;
  final StrategyChips strategies;

  static const DashboardData empty = DashboardData(
    indices: [],
    summary: PortfolioSummary.empty,
  );

  DashboardData copyWith({
    List<MarketIndex>? indices,
    PortfolioSummary? summary,
    List<CommodityQuote>? commodities,
    VixData? vix,
  }) => DashboardData(
        indices: indices ?? this.indices,
        summary: summary ?? this.summary,
        globalIndices: globalIndices,
        globalIndicesAvailable: globalIndicesAvailable,
        commodities: commodities ?? this.commodities,
        vix: vix ?? this.vix,
        nextExpiry: nextExpiry,
        fiiDii: fiiDii,
        news: news,
        sentiment: sentiment,
        todayPnl: todayPnl,
        margin: margin,
        strategies: strategies,
      );

  static const Map<String, String> indexNames = {'13': 'NIFTY', '25': 'BANKNIFTY', '51': 'SENSEX'};

  factory DashboardData.fromJson(Map<String, dynamic> json) {
    final indicesJson = json['indices'] as Map<String, dynamic>? ?? {};
    final indices = indexNames.entries.map((e) {
      final bySymbol = indicesJson[e.value] as Map<String, dynamic>? ?? {'available': false};
      final sid = bySymbol['security_id']?.toString() ?? e.key;
      return MarketIndex.fromJson(sid, e.value, bySymbol);
    }).toList();

    final globalIndicesJson = json['global_indices'] as Map<String, dynamic>? ?? {};
    final globalIndicesList = (globalIndicesJson['indices'] as List<dynamic>? ?? [])
        .map((q) => GlobalIndexQuote.fromJson(q as Map<String, dynamic>))
        .toList();

    final commoditiesList = (json['commodities'] as List<dynamic>? ?? [])
        .map((c) => CommodityQuote.fromJson(c as Map<String, dynamic>))
        .toList();

    return DashboardData(
      indices: indices,
      summary: PortfolioSummary.fromJson(json['portfolio'] as Map<String, dynamic>? ?? {}),
      globalIndices: globalIndicesList,
      globalIndicesAvailable: globalIndicesJson['available'] == true,
      commodities: commoditiesList,
      vix: VixData.fromJson(json['vix'] as Map<String, dynamic>? ?? {}),
      nextExpiry: NextExpiry.fromJson(json['next_expiry'] as Map<String, dynamic>? ?? {}),
      fiiDii: FiiDiiHistory.fromJson(json['fii_dii'] as Map<String, dynamic>? ?? {}),
      news: NewsFeed.fromJson(json['news'] as Map<String, dynamic>? ?? {}),
      sentiment: SentimentData.fromJson(json['sentiment'] as Map<String, dynamic>? ?? {}),
      todayPnl: TodayPnl.fromJson(json['today_pnl'] as Map<String, dynamic>? ?? {}),
      margin: MarginSnapshot.fromJson(json['margin'] as Map<String, dynamic>? ?? {}),
      strategies: StrategyChips.fromJson(json['strategies'] as Map<String, dynamic>? ?? {}),
    );
  }
}
