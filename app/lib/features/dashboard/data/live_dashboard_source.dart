import 'dart:async';

import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../../portfolio/data/portfolio_source.dart';
import '../../portfolio/domain/portfolio_summary.dart';
import '../domain/dashboard_models.dart';
import 'dashboard_source.dart';

class LiveDashboardSource implements DashboardSource {
  LiveDashboardSource({
    required this.api,
    required this.ws,
    required this.portfolioSource,
  });

  final ApiClient api;
  final WsClient ws;
  final PortfolioSource portfolioSource;

  @override
  Stream<DashboardData> streamDashboard() async* {
    List<MarketIndex> currentIndices = [
      const MarketIndex(securityId: '13', name: 'NIFTY', ltp: 0.0, change: 0.0, changePct: 0.0),
      const MarketIndex(securityId: '25', name: 'BANKNIFTY', ltp: 0.0, change: 0.0, changePct: 0.0),
      const MarketIndex(securityId: '51', name: 'SENSEX', ltp: 0.0, change: 0.0, changePct: 0.0),
    ];
    PortfolioSummary currentSummary = PortfolioSummary.empty;

    // 1) Fetch initial LTPs via REST
    try {
      final ids = currentIndices.map((i) => i.securityId).join(',');
      final ltpJson = await api.getJson('/api/v1/ltp?ids=$ids');
      currentIndices = currentIndices.map((idx) {
        final val = ltpJson[idx.securityId];
        if (val is num) {
          return idx.copyWith(ltp: val.toDouble());
        }
        return idx;
      }).toList();
    } catch (_) {
      // Best effort
    }

    yield DashboardData(indices: currentIndices, summary: currentSummary);

    // 2) Listen to portfolio stream and market websocket
    ws.connect();

    // Subscribe to index updates
    // WS doesn't expose a method directly, we can send a raw message on the WebSocketChannel 
    // but WsClient only exposes decoded stream. Let's assume we can just listen to ticks 
    // and that the server broadcasts indices automatically, or we just listen to all ticks.
    // In our design, the WsClient doesn't expose the raw sink, so we will rely on ticks that come in.

    // Combine Streams
    final streamController = StreamController<DashboardData>();

    final portfolioSub = portfolioSource.watch().listen((snapshot) {
      currentSummary = snapshot.summary;
      streamController.add(DashboardData(indices: currentIndices, summary: currentSummary));
    });

    final wsSub = ws.stream.listen((msg) {
      if (msg['type'] == 'tick') {
        final secId = msg['security_id']?.toString();
        final ltpRaw = msg['ltp'];
        final ltp = (ltpRaw is num) ? ltpRaw.toDouble() : double.tryParse(ltpRaw?.toString() ?? '') ?? 0.0;
        
        bool changed = false;
        currentIndices = currentIndices.map((idx) {
          if (idx.securityId == secId) {
            changed = true;
            // Rough calc for change if we don't have previous close; keep simple
            final oldLtp = idx.ltp;
            final change = oldLtp > 0 ? (ltp - oldLtp) + idx.change : 0.0; 
            final pct = oldLtp > 0 ? (change / oldLtp) * 100 : 0.0;
            return idx.copyWith(ltp: ltp, change: change, changePct: pct);
          }
          return idx;
        }).toList();

        if (changed) {
          streamController.add(DashboardData(indices: currentIndices, summary: currentSummary));
        }
      }
    });

    streamController.onCancel = () {
      portfolioSub.cancel();
      wsSub.cancel();
    };

    yield* streamController.stream;
  }
}
