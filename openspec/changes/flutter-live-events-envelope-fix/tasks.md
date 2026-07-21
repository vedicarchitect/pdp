# Tasks

## 1. Fix

- [x] 1.1 `live_events_source.dart`: read the REST event list from `items` (fall back to
      `events`) so the `Page` envelope populates the feed.
- [x] 1.2 `events_models.dart` (`AppEvent.fromJson`): read `underlying`/`timeframe`/`title`
      top-level first, then from the nested `data` map.

## 2. Verify

- [x] 2.1 Dart unit test (`app/test/live_events_source_test.dart`) pins the `Page[EventOut]`
      contract: items-key list, data-nested field mapping, and top-level precedence.
- [x] 2.2 `flutter analyze --fatal-infos`: "No issues found!" (exit 0). New Dart test file
      passes (3/3); full `flutter test` to be re-run alongside the console change.
- [x] 2.3 `openspec validate --strict flutter-live-events-envelope-fix` — valid.
- [ ] 2.4 Live smoke: with events present in the backend, the Live Events sidebar renders them
      (no "No events to show").

## 3. Archive

- [ ] 3.1 `openspec archive flutter-live-events-envelope-fix` once 2.4 confirmed in the app.
