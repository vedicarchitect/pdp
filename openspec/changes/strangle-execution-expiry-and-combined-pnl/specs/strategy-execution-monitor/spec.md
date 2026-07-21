## MODIFIED Requirements

### Requirement: Realtime strangle monitor endpoint

The system SHALL expose `GET /api/v1/strangle/monitor` that returns a single JSON document describing
the running directional strangle, or HTTP 404 when no `DirectionalStrangle` is running. The endpoint
SHALL be read-only and serialise all `Decimal` values to float. It SHALL reuse the running instance via
`_get_strangle(request)` and MUST NOT mutate strategy state.

The document SHALL contain: `indices` (NIFTY/BANKNIFTY/SENSEX spot LTP and future LTP, read from Redis
`ltp:{security_id}`, with `future` null when the strategy has no `futures_security_id`); `groups` (legs
grouped by underlying, each leg carrying `strike`, `lots`, `is_hedge`, `entry_price`, `entry_time`,
`entry_reason`, `expiry`, `dte`, `ltp`, `mtm`, and for non-hedge active strikes `delta`/`vega`/`gamma`/
`theta`/`oi`/`pcr`/`oi_change_day`); per-group and overall `totals` (`day_realized`, `day_unrealized`,
`day_pnl`); `status` (`bucket`, `score`, `done_for_day`, `started_at`, `n_open_shorts`, `n_open_hedges`,
`n_open_momentum`); `recent_events` (last N from the strategy `_activity` deque); and `indicators`.

Each leg SHALL carry `expiry` (ISO date string, from the already-resolved `OpenLeg.expiry`, or `null`
when unresolved) and `dte` (integer calendar days from today to expiry, server-computed, or `null` when
`expiry` is `null`). Per-group `totals.day_realized` SHALL be the real realized P&L for that underlying's
strategy instance (not a hardcoded `0.0`), and per-group `day_pnl` SHALL equal `day_realized +
day_unrealized`. A leg's `entry_reason` SHALL NOT contain the literal string `"None"` in place of a
bucket name; when the bucket is unset at construction time a stable placeholder SHALL be used.

#### Scenario: Monitor returns full snapshot when strangle running

- **WHEN** a `DirectionalStrangle` is running and `GET /api/v1/strangle/monitor` is called
- **THEN** the response is HTTP 200 with `indices`, `groups`, `totals`, `status`, `recent_events`, and `indicators` keys populated

#### Scenario: Leg carries expiry and DTE

- **WHEN** a leg has a resolved `OpenLeg.expiry`
- **THEN** its monitor payload includes `expiry` as an ISO date and `dte` as the integer calendar days
  from today to that expiry; a leg with no resolved expiry has both `expiry` and `dte` as `null`

#### Scenario: Per-underlying realized P&L is real

- **WHEN** a strategy instance for an underlying has non-zero realized P&L for the day
- **THEN** that underlying's `groups[].totals.day_realized` reflects the real value and `day_pnl`
  equals `day_realized + day_unrealized`, not a hardcoded `0.0`

#### Scenario: Entry reason never shows the literal None

- **WHEN** a leg is opened before the bias bucket is set
- **THEN** its `entry_reason` does not contain the literal substring `"None"` as the bucket name

#### Scenario: Monitor 404 when no strangle

- **WHEN** no `DirectionalStrangle` instance is running and the endpoint is called
- **THEN** the response is HTTP 404

#### Scenario: Future LTP null when futures sid unset

- **WHEN** the running strategy has no `futures_security_id` configured
- **THEN** the corresponding index `future` field is `null` while `spot` is still populated

### Requirement: Flutter Strategy Execution panel

The app SHALL present a "Strategy Execution" tab in the Manage hub that consumes
`GET /api/v1/strangle/monitor` and refreshes at least every 2 seconds. It SHALL show a top index bar
(NIFTY/BANKNIFTY/SENSEX spot + future), a positions table grouped by underlying with per-index and
overall P&L totals colored via `AppColors.profit`/`AppColors.loss`, a strategy status badge, and a
bottom indicator matrix. The polling stream SHALL cancel its timer on disposal so no subscription leaks.

Each underlying group SHALL display a combined realized+unrealized P&L line (per-underlying, mirroring
the overall totals line). Each leg row SHALL display its DTE (e.g. "DTE 3") sourced from the monitor
`dte` field, so a rehydrated multi-day-old position is distinguishable from a same-day entry without
relying on `entry_time` (which is legitimately null for rehydrated legs). The indicator matrix's
horizontal overflow SHALL be discoverable — the rightmost columns SHALL be reachable via a visible
scroll affordance and/or a panel that widens on large windows, rather than being clipped off-screen.

#### Scenario: Tab renders live monitor

- **WHEN** the user opens Manage → Strategy Execution while the strangle is running
- **THEN** the index bar, grouped positions, totals, and indicator matrix render and update within ~2 seconds

#### Scenario: Combined P&L line per underlying

- **WHEN** an underlying group has both realized and unrealized P&L
- **THEN** its group header shows a combined P&L line equal to realized + unrealized, colored profit/loss

#### Scenario: DTE shown per leg

- **WHEN** a leg's monitor payload carries a non-null `dte`
- **THEN** the leg row renders the DTE, so a rehydrated older position is visually distinguishable from a same-day entry

#### Scenario: Indicator matrix columns are reachable

- **WHEN** the execution tab is shown on a wide window and the indicator matrix has more columns than fit
- **THEN** the rightmost columns are reachable via a visible horizontal scroll affordance (not clipped without an affordance)

#### Scenario: Stream disposed cleanly

- **WHEN** the user navigates away from the Strategy Execution tab
- **THEN** the polling timer and stream subscription are cancelled
