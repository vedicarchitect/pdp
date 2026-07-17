# execution-panel-freshness-and-events

## Why

During the 2026-07-17 paper-trading investigation the Execution Console looked "stale or not
connecting" with no way to tell why: an unconverged/disconnected cell renders `--`, which is
visually identical to a live cell whose true value happens to be null-ish, so the operator had no
signal to distinguish "quiet, nothing to report" from "the poll or the feed is actually stuck."
Separately, `GET /api/v1/events` was 500ing on every call (6× logged that day): `routes.py`'s
`list_events` handler has always forwarded `offset=pagination.offset` (from `PaginationParams`,
default 0) to `EventStore.list_events()`, but the store's signature never accepted an `offset`
keyword, so `TypeError: list_events() got an unexpected keyword argument 'offset'` fired on the
very first call, default or not.

Finally, the monitor snapshot's `recent_events` field has been round-tripped into the Flutter
`MonitorSnapshot` model since the original `strategy-execution-panel` change, but the Strategy
Execution tab never rendered it — so the `ENTRY_ABORTED` event added by
`strangle-entry-fill-race-and-latch` (a strategy that goes quiet after every entry aborts) had
nowhere to surface in the UI even though the backend was already emitting it correctly.

VIX wiring is explicitly out of scope here (the VIX gate is disabled; `ltp:21` being live while
bias reports `vix_unavailable` is cosmetic and not addressed by this change) — user-confirmed.

## What Changes

- **Fix the `/api/v1/events` 500**: `EventStore.list_events()` gains an `offset: int = 0`
  parameter, applied as `skip` on the Mongo cursor. No route change needed — `routes.py` was
  already passing the right value to a store that didn't accept it.
- **Freshness signal on the monitor payload**: `GET /api/v1/strangle/monitor` gains `as_of` (server
  UTC timestamp when the payload was built) and, per index, `spot_age_s` (seconds since the last
  tick, read from the existing `ltp_ts:{security_id}` Redis key the tick router already writes on
  every tick with a 5s TTL). `spot_age_s` is `null` when no tick has landed in the last 5 seconds —
  an honest "no data", not a guessed value.
- **Freshness badge in the Execution panel**: a new indicator combines `as_of` age (catches a stuck
  client poll or a hung backend) and the worst per-index `spot_age_s` (catches a dead market feed
  even when the backend itself is responding) into a single live/stale cue, so `--` cells can be
  read against a visible "is this even current" signal instead of in isolation.
- **Recent-activity strip**: the Strategy Execution tab now renders `recent_events` (newest-first,
  capped at 5), with `entry_aborted` events specifically called out (warning icon + emphasis) so an
  aborted entry is visible in the UI the moment it happens, not just in the backend log.

## Impact

- Affected specs: `events` (MODIFIED — `list_events` accepts `offset`), `strategy-execution-monitor`
  (MODIFIED — monitor payload freshness fields + panel freshness badge + recent-activity strip).
- Affected code: `backend/pdp/events/store.py`, `backend/pdp/strategy/routes.py`,
  `backend/pdp/strategy/schemas.py`, `app/lib/features/manage/domain/execution_models.dart`,
  `app/lib/features/manage/presentation/tabs/strategy_execution_tab.dart`.
- No schema/migration changes; no VIX plumbing touched (de-scoped per user).
