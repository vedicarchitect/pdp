import 'portfolio_summary.dart';
import 'position.dart';

/// An immutable point-in-time view of the portfolio: totals + open positions.
class PortfolioSnapshot {
  const PortfolioSnapshot({required this.summary, required this.positions});

  final PortfolioSummary summary;
  final List<Position> positions;

  static const PortfolioSnapshot empty = PortfolioSnapshot(
    summary: PortfolioSummary.empty,
    positions: <Position>[],
  );
}
