import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/network/api_client.dart';
import '../../../core/network/ws_client.dart';
import '../data/holdings_repository.dart';
import '../domain/holdings_models.dart';

final holdingsRepositoryProvider = Provider<HoldingsRepository>((ref) {
  return HoldingsRepository(ApiClient());
});

final holdingsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) {
  return ref.watch(holdingsRepositoryProvider).getHoldings();
});

final positionsProvider = FutureProvider.autoDispose<List<PositionDetail>>((ref) {
  return ref.watch(holdingsRepositoryProvider).getPositions();
});

final livePositionsProvider = StreamProvider.autoDispose<List<PositionDetail>>((ref) async* {
  final initialPositions = await ref.watch(positionsProvider.future);
  if (initialPositions.isEmpty) {
    yield [];
    return;
  }

  var current = initialPositions.toList();
  yield current;

  final ws = WsClient(url: '${AppConfig.current.wsBase}/ws/market');
  ws.connect();
  ref.onDispose(ws.dispose);

  await for (final msg in ws.stream) {
    if (msg['type'] != 'tick') continue;
    final secId = msg['security_id']?.toString();
    if (secId == null) continue;

    final ltpRaw = msg['ltp'];
    final ltp = (ltpRaw is num) ? ltpRaw.toDouble() : double.tryParse(ltpRaw?.toString() ?? '');
    if (ltp == null) continue;

    var changed = false;
    current = current.map((p) {
      if (p.securityId == secId) {
        changed = true;
        return p.copyWith(ltp: ltp);
      }
      return p;
    }).toList();

    if (changed) {
      yield current;
    }
  }
});
