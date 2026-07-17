# Tasks — execution-panel-freshness-and-events

## 0. Diagnostics (read-only, done)
- [x] 0.1 Confirmed the `/api/v1/events` 500 root cause: `routes.py::list_events` calls
      `store.list_events(..., offset=pagination.offset)`, but `EventStore.list_events()` had no
      `offset` parameter — `TypeError` on every call, not only explicitly-paginated ones.
- [x] 0.2 Confirmed `MonitorSnapshot.recentEvents` is already parsed from `recent_events` but never
      rendered anywhere in `strategy_execution_tab.dart` — the ENTRY_ABORTED event added by
      `strangle-entry-fill-race-and-latch` already flows into `_activity`/`recent_events`
      (`_emit_event` appends to `self._activity`), so no backend event-plumbing change is needed —
      only the panel needs to render what's already there.
- [x] 0.3 Confirmed `ltp_ts:{security_id}` (epoch seconds, TTL=5s) is already written by
      `TickRouter._handle` on every tick — reused as the spot-freshness source rather than adding a
      new Redis key.

## 1. Fix the `/api/v1/events` 500
- [x] 1.1 `EventStore.list_events()` gains `offset: int = 0`, applied as `skip=max(0, offset)` on
      the Mongo cursor.
- [x] 1.2 Tests: `tests/events/test_store.py` (offset applied, defaults to 0, no-collection path);
      `tests/events/test_routes.py` (`GET /api/v1/events` with default and explicit pagination both
      return 200, not 500).

## 2. Monitor payload freshness fields
- [x] 2.1 `_get_ltp_age_redis(redis, sid)` reads `ltp_ts:{sid}`, returns seconds-since-tick or
      `None` when absent/expired.
- [x] 2.2 Per-index `spot_age_s` added alongside `spot`/`future` in the `indices` block.
- [x] 2.3 Top-level `as_of` (server UTC ISO timestamp) added to the payload; `StrangleMonitorOut`
      schema gains the `as_of: str` field.
- [x] 2.4 Tests: `tests/strategy/test_monitor_route.py` — `as_of` present, `spot_age_s` present
      (None when no tick, a small positive value when a tick was recorded 2s ago).

## 3. Freshness badge (Flutter)
- [x] 3.1 `IndexPrice` gains `spotAgeS`; `MonitorSnapshot` gains `asOf` (parsed from `as_of`).
- [x] 3.2 `_FreshnessBadge` combines `as_of` age and the worst `spot_age_s` across indices into a
      single live/stale cue (>10s combined slack — 5s Redis TTL + 2s poll interval + buffer — or no
      live tick at all renders stale), wired into `_OverallStatusBar`.
- [x] 3.3 Widget tests: no-timestamp-and-no-tick renders "feed stale"; a fresh `as_of` + recent tick
      renders live; a stale `as_of` renders stale even with a live tick present (payload-poll
      staleness must not be masked by a coincidentally-fresh tick).

## 4. Recent-activity strip (Flutter)
- [x] 4.1 `_RecentEventsStrip` + `_EventLine` render `snap.recentEvents` newest-first, capped to 5.
- [x] 4.2 `entry_aborted` events render with a warning icon + emphasis and the `reason` field;
      other event types render as routine activity (human-readable type, no warning treatment).
- [x] 4.3 Widget tests: hidden when empty; `entry_aborted` shows warning icon + reason; a
      non-aborted event renders without the warning icon; more than 5 events are capped to 5.

## 5. Docs + validation
- [x] 5.1 `task test` full green. **1194 passed** (up from 1187 pre-change; +7 new tests).
- [x] 5.2 `flutter analyze --fatal-infos` + `flutter test`. **No issues found; 41/41 passed**
      (up from 34; +7 new widget tests).
- [x] 5.3 `openspec validate --strict execution-panel-freshness-and-events`.

## 6. Verify + archive
- [ ] 6.1 Live/boot smoke on the next market day: freshness badge shows "live" during market hours
      and flips to stale within ~10s of a feed interruption; an `entry_aborted` event (if any fires)
      renders in the strip; `GET /api/v1/events` no longer 500s in production logs.
- [ ] 6.2 `openspec archive execution-panel-freshness-and-events`.
