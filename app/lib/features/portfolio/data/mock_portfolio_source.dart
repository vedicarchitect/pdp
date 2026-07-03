import 'dart:async';
import 'dart:math';

import '../domain/portfolio_snapshot.dart';
import '../domain/portfolio_summary.dart';
import '../domain/position.dart';
import 'portfolio_source.dart';

/// Simulates a live portfolio feed with zero backend. Seeds a handful of option
/// positions and nudges their unrealized P&L on a periodic tick (bounded random
/// walk), so the UI looks alive for demos and tests.
class MockPortfolioSource implements PortfolioSource {
  MockPortfolioSource({this.tick = const Duration(milliseconds: 600)});

  final Duration tick;
  final Random _rng = Random();

  @override
  Stream<PortfolioSnapshot> watch() async* {
    var positions = _seed();
    yield _snapshot(positions);
    yield* Stream.periodic(tick, (_) {
      positions = positions.map(_jitter).toList(growable: false);
      return _snapshot(positions);
    });
  }

  List<Position> _seed() => const [
        Position(
          securityId: '40123',
          exchangeSegment: 'NSE_FNO',
          product: 'INTRADAY',
          netQty: -75,
          avgPrice: 142.5,
          realizedPnl: 0,
          unrealizedPnl: 1875,
          symbol: 'NIFTY 24500 CE',
        ),
        Position(
          securityId: '40987',
          exchangeSegment: 'NSE_FNO',
          product: 'INTRADAY',
          netQty: -75,
          avgPrice: 138.0,
          realizedPnl: 0,
          unrealizedPnl: -1320,
          symbol: 'NIFTY 24300 PE',
        ),
        Position(
          securityId: '41555',
          exchangeSegment: 'NSE_FNO',
          product: 'MARGIN',
          netQty: -15,
          avgPrice: 410.0,
          realizedPnl: 2400,
          unrealizedPnl: 980,
          symbol: 'BANKNIFTY 51000 CE',
        ),
        Position(
          securityId: '41777',
          exchangeSegment: 'NSE_FNO',
          product: 'MARGIN',
          netQty: -15,
          avgPrice: 395.0,
          realizedPnl: 0,
          unrealizedPnl: -640,
          symbol: 'BANKNIFTY 50500 PE',
        ),
      ];

  Position _jitter(Position p) {
    final step = (_rng.nextDouble() - 0.48) * 350;
    final next = (p.unrealizedPnl + step).clamp(-9000.0, 9000.0).toDouble();
    return p.copyWith(unrealizedPnl: next);
  }

  PortfolioSnapshot _snapshot(List<Position> positions) {
    var unreal = 0.0;
    var real = 0.0;
    var open = 0;
    for (final p in positions) {
      unreal += p.unrealizedPnl;
      real += p.realizedPnl;
      if (p.netQty != 0) open++;
    }
    return PortfolioSnapshot(
      summary: PortfolioSummary(
        totalUnrealizedPnl: unreal,
        totalRealizedPnl: real,
        dayPnl: unreal + real,
        openPositions: open,
        mode: 'paper',
      ),
      positions: positions,
    );
  }
}
