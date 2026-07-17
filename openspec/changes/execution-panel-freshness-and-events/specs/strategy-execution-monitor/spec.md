## MODIFIED Requirements

### Requirement: Realtime strangle monitor endpoint

The system SHALL expose `GET /api/v1/strangle/monitor` that returns a single JSON document describing
the running directional strangle, or HTTP 404 when no `DirectionalStrangle` is running. The endpoint
SHALL be read-only and serialise all `Decimal` values to float. It SHALL reuse the running instance via
`_get_strangle(request)` and MUST NOT mutate strategy state.

The document SHALL contain: `as_of` (server UTC timestamp, ISO-8601, taken when the payload is built —
the freshness anchor a client uses to tell a live snapshot from a stuck poll); `indices` (NIFTY/
BANKNIFTY/SENSEX spot LTP and future LTP, read from Redis `ltp:{security_id}`, with `future` null when
the strategy has no `futures_security_id`, and `spot_age_s` — seconds since the last tick, read from
`ltp_ts:{security_id}`, `null` when no tick has landed within its 5s TTL); `groups` (legs
grouped by underlying, each leg carrying `strike`, `lots`, `is_hedge`, `entry_price`, `entry_time`,
`entry_reason`, `ltp`, `mtm`, and for non-hedge active strikes `delta`/`vega`/`gamma`/`theta`/`oi`/
`pcr`/`oi_change_day`); per-group and overall `totals` (`day_realized`, `day_unrealized`, `day_pnl`);
`status` (`bucket`, `score`, `done_for_day`, `started_at`, `n_open_shorts`, `n_open_hedges`,
`n_open_momentum`); `recent_events` (last N from the strategy `_activity` deque); and `indicators`.

#### Scenario: Monitor returns full snapshot when strangle running

- **WHEN** a `DirectionalStrangle` is running and `GET /api/v1/strangle/monitor` is called
- **THEN** the response is HTTP 200 with `as_of`, `indices`, `groups`, `totals`, `status`, `recent_events`, and `indicators` keys populated

#### Scenario: Monitor 404 when no strangle

- **WHEN** no `DirectionalStrangle` instance is running and the endpoint is called
- **THEN** the response is HTTP 404

#### Scenario: Future LTP null when futures sid unset

- **WHEN** the running strategy has no `futures_security_id` configured
- **THEN** the corresponding index `future` field is `null` while `spot` is still populated

#### Scenario: Spot age reflects real tick recency

- **WHEN** an index's `ltp_ts:{security_id}` key was written 2 seconds ago
- **THEN** that index's `spot_age_s` is a small positive number, not `null` and not a guessed default

#### Scenario: Spot age is honestly null when the feed is dead

- **WHEN** an index has had no tick within the last 5 seconds (`ltp_ts:{security_id}` expired or was never set)
- **THEN** that index's `spot_age_s` is `null` rather than a stale or fabricated value

### Requirement: Flutter Strategy Execution panel

The app SHALL present a "Strategy Execution" tab in the Manage hub that consumes
`GET /api/v1/strangle/monitor` and refreshes at least every 2 seconds. It SHALL show a top index bar
(NIFTY/BANKNIFTY/SENSEX spot + future), a positions table grouped by underlying with per-index and
overall P&L totals colored via `AppColors.profit`/`AppColors.loss`, a strategy status badge, a
freshness indicator, a recent-activity strip, and a bottom indicator matrix. The polling stream SHALL
cancel its timer on disposal so no subscription leaks.

The freshness indicator SHALL derive its live/stale state from both the payload's `as_of` age and the
worst per-index `spot_age_s`, rendering visibly as stale (not merely omitted) when either signal
indicates the snapshot is not current. The recent-activity strip SHALL render the monitor payload's
`recent_events` newest-first, capped to a small fixed count, and SHALL visually distinguish an
`entry_aborted` event from routine activity so a strategy that silently stopped opening new legs is
noticeable without reading the backend log.

#### Scenario: Tab renders live monitor

- **WHEN** the user opens Manage → Strategy Execution while the strangle is running
- **THEN** the index bar, grouped positions, totals, freshness indicator, recent-activity strip, and indicator matrix render and update within ~2 seconds

#### Scenario: Stream disposed cleanly

- **WHEN** the user navigates away from the Strategy Execution tab
- **THEN** the polling timer and stream subscription are cancelled

#### Scenario: Freshness indicator reads stale when the feed has gone dead

- **WHEN** every index's `spot_age_s` is `null` (no live tick) regardless of how recently the payload itself was polled
- **THEN** the freshness indicator renders in its stale state, not its live state

#### Scenario: An aborted entry is visible in the panel

- **WHEN** the monitor payload's `recent_events` contains an `entry_aborted` event
- **THEN** the recent-activity strip renders that event with a distinct (warning) visual treatment, including its reason
