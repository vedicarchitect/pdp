import 'dart:async';

import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../domain/portfolio_snapshot.dart';
import '../domain/portfolio_summary.dart';
import '../domain/position.dart';
import 'portfolio_source.dart';

/// Real backend source: a REST snapshot seed followed by the `/ws/portfolio`
/// stream. The backend re-sends a full `portfolio_update` on (re)connect, so no
/// gap-reconciliation is needed here — each message replaces the snapshot.
///
/// NOTE: the `/ws/portfolio` `positions` array is produced by
/// `PortfolioService.get_snapshot()`; [Position.fromJson] is tolerant of field
/// differences. If a live run shows missing fields, align the keys here.
class LivePortfolioSource implements PortfolioSource {
  LivePortfolioSource({required this.api, required this.ws});

  final ApiClient api;
  final WsClient ws;

  @override
  Stream<PortfolioSnapshot> watch() async* {
    var snapshot = PortfolioSnapshot.empty;

    // 1) REST seed (best-effort; the WS will also deliver an initial snapshot).
    try {
      final summaryJson = await api.getJson('/api/v1/portfolio/summary');
      final positionsJson = await api.getJson('/api/v1/portfolio/positions');
      snapshot = PortfolioSnapshot(
        summary: PortfolioSummary.fromJson(summaryJson),
        positions: _parsePositions(positionsJson['positions']),
      );
      yield snapshot;
    } catch (_) {
      // Ignore seed failure; rely on the WS stream below.
    }

    // 2) Live stream.
    ws.connect();
    await for (final msg in ws.stream) {
      if (msg['type'] != 'portfolio_update') continue;
      final summaryRaw = msg['summary'];
      snapshot = PortfolioSnapshot(
        summary: summaryRaw is Map<String, dynamic>
            ? PortfolioSummary.fromJson(summaryRaw)
            : snapshot.summary,
        positions: _parsePositions(msg['positions']),
      );
      yield snapshot;
    }
  }

  List<Position> _parsePositions(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map<String, dynamic>>()
        .map(Position.fromJson)
        .toList(growable: false);
  }
}
