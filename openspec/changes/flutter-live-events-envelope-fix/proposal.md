# flutter-live-events-envelope-fix

## Why

Live-verified 2026-07-20 (user viewing the app, backend healthy): the Live Events sidebar
renders "No events to show" even though `GET /api/v1/events?limit=10` returns rich real events
(EMA_CROSS, CONFLUENCE_ZONE, SAFE_TO_EXIT_TRAIL, MTM_SWING, PCR_SHIFT). This is purely a
frontend deserialization bug.

`LiveEventsSource._init` correctly calls `GET /api/v1/events?limit=50`
([live_events_source.dart:30](../../../app/lib/features/events/data/live_events_source.dart#L30)),
but the next line reads the wrong envelope key:
[live_events_source.dart:31](../../../app/lib/features/events/data/live_events_source.dart#L31)
does `eventsJson['events']`, while the backend returns a `Page` envelope whose list key is
**`items`** ([schemas.py:6-10](../../../backend/pdp/schemas.py#L6-L10); pinned by
`resp.json() == {"items": [], ...}` in
[test_routes.py:28](../../../backend/tests/events/test_routes.py#L28)). `['events']` is always
`null` → `?? []` → empty list → "No events to show", regardless of backend content. No filter
is involved.

Secondary (same feature area): `AppEvent.fromJson`
([events_models.dart:24-40](../../../app/lib/features/events/domain/events_models.dart#L24-L40))
reads `underlying`/`timeframe`/`title` as top-level keys, but the REST `EventOut` nests those
inside `data` ([schemas.py:4-11](../../../backend/pdp/events/schemas.py#L4-L11)) — so once
events render, those tile labels are null on REST-sourced events (the WS frame may still carry
them top-level).

## What Changes

- `LiveEventsSource._init` reads the event list from `items` (with an `events` fallback for
  safety) so the REST backfill actually populates the feed.
- `AppEvent.fromJson` reads `underlying`/`timeframe`/`title` top-level first, then falls back to
  the nested `data` map, so both the REST envelope and the WS frame populate those labels.
- A Dart unit test pins the `Page[EventOut]` deserialization contract (items key + data-nested
  fields + top-level precedence).

## Impact

- Affected specs: `event-feed-ui` (tightens the existing "Backend REST backfill parses"
  scenario to pin the `Page`-envelope `items` key and the `data`-nested field mapping).
- Affected code: `app/lib/features/events/data/live_events_source.dart`,
  `app/lib/features/events/domain/events_models.dart`, new
  `app/test/live_events_source_test.dart`.
- No backend change — the backend was returning the correct payload all along.
- Relates to the in-flight `execution-panel-freshness-and-events`; this fix is confined to the
  global `features/events/` sidebar and does not touch the strangle console.
