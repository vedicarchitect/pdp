## ADDED Requirements

### Requirement: Realtime strangle monitor endpoint

The system SHALL expose `GET /api/v1/strangle/monitor` that returns a single JSON document describing
the running directional strangle, or HTTP 404 when no `DirectionalStrangle` is running. The endpoint
SHALL be read-only and serialise all `Decimal` values to float. It SHALL reuse the running instance via
`_get_strangle(request)` and MUST NOT mutate strategy state.

The document SHALL contain: `indices` (NIFTY/BANKNIFTY/SENSEX spot LTP and future LTP, read from Redis
`ltp:{security_id}`, with `future` null when the strategy has no `futures_security_id`); `groups` (legs
grouped by underlying, each leg carrying `strike`, `lots`, `is_hedge`, `entry_price`, `entry_time`,
`entry_reason`, `ltp`, `mtm`, and for non-hedge active strikes `delta`/`vega`/`gamma`/`theta`/`oi`/
`pcr`/`oi_change_day`); per-group and overall `totals` (`day_realized`, `day_unrealized`, `day_pnl`);
`status` (`bucket`, `score`, `done_for_day`, `started_at`, `n_open_shorts`, `n_open_hedges`,
`n_open_momentum`); `recent_events` (last N from the strategy `_activity` deque); and `indicators`.

#### Scenario: Monitor returns full snapshot when strangle running

- **WHEN** a `DirectionalStrangle` is running and `GET /api/v1/strangle/monitor` is called
- **THEN** the response is HTTP 200 with `indices`, `groups`, `totals`, `status`, `recent_events`, and `indicators` keys populated

#### Scenario: Monitor 404 when no strangle

- **WHEN** no `DirectionalStrangle` instance is running and the endpoint is called
- **THEN** the response is HTTP 404

#### Scenario: Future LTP null when futures sid unset

- **WHEN** the running strategy has no `futures_security_id` configured
- **THEN** the corresponding index `future` field is `null` while `spot` is still populated

### Requirement: Monitor Greeks, OI and PCR per active strike

The system SHALL include delta, vega, gamma, theta, open interest, strike PCR, and OI-change-since-day-
start for each active non-hedge strike, sourced from the latest `option_chains` snapshot. OI-change MUST
be computed against the earliest snapshot of the current trading day for that underlying/strike. When no
chain snapshot is available these fields SHALL be `null` rather than fabricated.

#### Scenario: Greeks present when chain snapshot exists

- **WHEN** the options poller has a current `option_chains` snapshot and a non-hedge short strike is open
- **THEN** that leg includes non-null `delta`, `vega`, `gamma`, `theta`, `oi`, `pcr`, and `oi_change_day`

#### Scenario: Greeks null without chain data

- **WHEN** no `option_chains` snapshot exists for the strike
- **THEN** the leg's Greeks/OI/PCR fields are `null`

### Requirement: Monitor indicator matrix

The system SHALL include an indicator matrix for the three indices and each active non-hedge strike,
spanning timeframes `5m`, `15m`, `30m`, `1H`, `1D`, with EMA(9/20/50/100), SuperTrend(10,2) value and
direction, and Parabolic SAR per timeframe, plus daily and weekly Camarilla (pp/r3/r4/s3/s4) and
PDH/PDL/PWH/PWL. Pivot and period levels are per-session constants and SHALL be read once per request
from the indicator engine, not recomputed.

#### Scenario: Matrix covers indices and active strikes

- **WHEN** the monitor is requested with two short legs open
- **THEN** `indicators` contains entries for NIFTY/BANKNIFTY/SENSEX and the two active non-hedge strike security ids

#### Scenario: Weekly Camarilla populated

- **WHEN** weekly (`1w`) bars are available for an index
- **THEN** that index's `camarilla_weekly` contains non-null pp/r3/r4/s3/s4

### Requirement: Flutter Strategy Execution panel

The app SHALL present a "Strategy Execution" tab in the Manage hub that consumes
`GET /api/v1/strangle/monitor` and refreshes at least every 2 seconds. It SHALL show a top index bar
(NIFTY/BANKNIFTY/SENSEX spot + future), a positions table grouped by underlying with per-index and
overall P&L totals colored via `AppColors.profit`/`AppColors.loss`, a strategy status badge, and a
bottom indicator matrix. The polling stream SHALL cancel its timer on disposal so no subscription leaks.

#### Scenario: Tab renders live monitor

- **WHEN** the user opens Manage → Strategy Execution while the strangle is running
- **THEN** the index bar, grouped positions, totals, and indicator matrix render and update within ~2 seconds

#### Scenario: Stream disposed cleanly

- **WHEN** the user navigates away from the Strategy Execution tab
- **THEN** the polling timer and stream subscription are cancelled
