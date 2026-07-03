import 'dart:async';

import '../domain/portfolio_snapshot.dart';

/// A source of live portfolio snapshots. Implemented by both the real backend
/// ([LivePortfolioSource]) and the offline simulation ([MockPortfolioSource]),
/// so the presentation layer never branches on data origin.
abstract interface class PortfolioSource {
  /// Emits an initial snapshot then a new snapshot on every update.
  Stream<PortfolioSnapshot> watch();
}
