import 'package:flutter_test/flutter_test.dart';

import 'package:pdp_app/features/events/domain/events_models.dart';

/// flutter-live-events-envelope-fix: the backend `GET /api/v1/events` returns a
/// `Page` envelope keyed `items` (pdp/schemas.py), and each `EventOut` nests
/// `underlying`/`timeframe`/`title` inside `data`. These tests pin the
/// deserialization contract so the Live Events sidebar renders real events
/// instead of "No events to show".
void main() {
  test('AppEvent.fromJson reads a real EventOut with data-nested fields', () {
    final json = {
      'id': 'e1',
      'ts': '2026-07-20T06:00:11Z',
      'event_type': 'EMA_CROSS',
      'severity': 'INFO',
      'security_id': '13',
      'message': 'EMA9 crossed EMA20',
      'data': {'underlying': 'NIFTY', 'timeframe': '5m', 'title': 'EMA cross'},
    };

    final evt = AppEvent.fromJson(json);

    expect(evt.id, 'e1');
    expect(evt.eventType, 'EMA_CROSS');
    expect(evt.severity, 'info'); // normalised lowercase
    expect(evt.securityId, '13');
    expect(evt.underlying, 'NIFTY'); // pulled from nested data
    expect(evt.timeframe, '5m');
    expect(evt.title, 'EMA cross');
    expect(evt.message, 'EMA9 crossed EMA20');
  });

  test('AppEvent.fromJson prefers top-level fields (WS frame shape)', () {
    // The WS frame (Event.to_dict()) may carry these top-level; that must win.
    final json = {
      'id': 'e2',
      'ts': '2026-07-20T06:00:12Z',
      'event_type': 'PCR_SHIFT',
      'severity': 'WARNING',
      'underlying': 'BANKNIFTY',
      'timeframe': '15m',
      'message': 'PCR shifted',
      'data': {'underlying': 'IGNORED', 'timeframe': 'IGNORED'},
    };

    final evt = AppEvent.fromJson(json);

    expect(evt.underlying, 'BANKNIFTY');
    expect(evt.timeframe, '15m');
    expect(evt.severity, 'warning');
  });

  test('a Page envelope exposes events under the items key', () {
    // Mirrors LiveEventsSource._init: read `items`, fall back to `events`.
    final page = {
      'items': [
        {'id': 'e1', 'ts': '2026-07-20T06:00:11Z', 'event_type': 'MTM_SWING', 'message': 'x'},
      ],
      'limit': 50,
      'offset': 0,
      'total': null,
    };

    final list = (page['items'] as List?) ?? (page['events'] as List?) ?? [];
    final events =
        list.map((e) => AppEvent.fromJson(e as Map<String, dynamic>)).toList();

    expect(events, hasLength(1));
    expect(events.first.eventType, 'MTM_SWING');
  });
}
