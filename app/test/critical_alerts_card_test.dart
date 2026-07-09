import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pdp_app/features/events/application/events_providers.dart';
import 'package:pdp_app/features/events/domain/events_models.dart';
import 'package:pdp_app/features/events/presentation/critical_alerts_card.dart';

/// Task 6.2 (strategy-critical-data-alerts): a NAKED_POSITION CRITICAL event
/// must surface in the CriticalAlertsCard banner.
void main() {
  testWidgets('renders a NAKED_POSITION critical event as an alert banner',
      (tester) async {
    final naked = AppEvent(
      id: 'e1',
      securityId: 'OPT1',
      underlying: 'NIFTY',
      timeframe: null,
      eventType: 'NAKED_POSITION',
      severity: 'critical',
      title: 'Naked short',
      message: 'Hedge unpriced — short leg left unhedged',
      timestamp: DateTime(2026, 7, 9, 10, 30),
    );
    final data = EventsData(
      events: [naked],
      config: const EventConfig(pushEnabled: false, eventTypePush: {}),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          eventsStreamProvider.overrideWith((ref) => Stream.value(data)),
        ],
        child: const MaterialApp(
          home: Scaffold(
            body: CustomScrollView(slivers: [CriticalAlertsCard()]),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.textContaining('CRITICAL: Naked short'), findsOneWidget);
    expect(find.textContaining('unhedged'), findsOneWidget);
  });

  testWidgets('non-critical events do not render a banner', (tester) async {
    final info = AppEvent(
      id: 'e2',
      securityId: '13',
      underlying: 'NIFTY',
      timeframe: '5m',
      eventType: 'EMA_CROSS',
      severity: 'info',
      title: 'EMA cross',
      message: 'EMA9 crossed EMA20',
      timestamp: DateTime(2026, 7, 9, 10, 31),
    );
    final data = EventsData(
      events: [info],
      config: const EventConfig(pushEnabled: false, eventTypePush: {}),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          eventsStreamProvider.overrideWith((ref) => Stream.value(data)),
        ],
        child: const MaterialApp(
          home: Scaffold(
            body: CustomScrollView(slivers: [CriticalAlertsCard()]),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.textContaining('CRITICAL'), findsNothing);
  });
}
