import 'dart:async';

import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../../portfolio/data/portfolio_source.dart';
import '../domain/dashboard_models.dart';
import 'dashboard_source.dart';

/// Seeds from a single `GET /api/v1/dashboard` call, then applies live deltas
/// over the existing `/ws/market` (index + commodity ticks) and
/// `/ws/portfolio` sockets. Slow-moving sections (global indices, news,
/// sentiment, FII/DII, next-expiry, today's P&L, margin, strategy chips) are
/// refreshed by periodically re-fetching the composed endpoint rather than
/// opening any new socket.
class LiveDashboardSource implements DashboardSource {
  LiveDashboardSource({
    required this.api,
    required this.ws,
    required this.portfolioSource,
    this.refreshInterval = const Duration(seconds: 60),
    this.sparklineLength = 30,
  });

  final ApiClient api;
  final WsClient ws;
  final PortfolioSource portfolioSource;
  final Duration refreshInterval;
  final int sparklineLength;

  final Map<String, List<double>> _sparklines = {};

  List<double> _pushSparkline(String securityId, double ltp) {
    final buf = _sparklines.putIfAbsent(securityId, () => []);
    buf.add(ltp);
    if (buf.length > sparklineLength) buf.removeAt(0);
    return List.unmodifiable(buf);
  }

  Future<DashboardData> _fetch() async {
    final json = await api.getJson('/api/v1/dashboard');
    return DashboardData.fromJson(json);
  }

  @override
  Stream<DashboardData> streamDashboard() async* {
    DashboardData current;
    try {
      current = await _fetch();
    } catch (_) {
      current = DashboardData.empty;
    }
    yield current;

    final controller = StreamController<DashboardData>();
    ws.connect();

    final portfolioSub = portfolioSource.watch().listen((snapshot) {
      current = current.copyWith(summary: snapshot.summary);
      controller.add(current);
    });

    final wsSub = ws.stream.listen((msg) {
      if (msg['type'] != 'tick') return;
      final secId = msg['security_id']?.toString();
      if (secId == null) return;
      final ltpRaw = msg['ltp'];
      final ltp = (ltpRaw is num) ? ltpRaw.toDouble() : double.tryParse(ltpRaw?.toString() ?? '');
      if (ltp == null) return;

      var changed = false;

      final updatedIndices = current.indices.map((idx) {
        if (idx.securityId == secId) {
          changed = true;
          return idx.copyWith(ltp: ltp, available: true, sparkline: _pushSparkline(secId, ltp));
        }
        return idx;
      }).toList();

      final updatedCommodities = current.commodities.map((c) {
        if (c.securityId == secId) {
          changed = true;
          return c.copyWith(ltp: ltp, available: true);
        }
        return c;
      }).toList();

      var updatedVix = current.vix;
      if (current.vix.securityId != null && secId == current.vix.securityId) {
        changed = true;
        updatedVix = VixData(available: true, securityId: current.vix.securityId, value: ltp);
      }

      if (changed) {
        current = current.copyWith(indices: updatedIndices, commodities: updatedCommodities, vix: updatedVix);
        controller.add(current);
      }
    });

    final refreshTimer = Timer.periodic(refreshInterval, (_) async {
      try {
        current = await _fetch();
        controller.add(current);
      } catch (_) {
        // Best effort — keep showing the last good snapshot.
      }
    });

    controller.onCancel = () {
      portfolioSub.cancel();
      wsSub.cancel();
      refreshTimer.cancel();
    };

    yield* controller.stream;
  }
}
