# strategy-execution-monitor Specification

## Purpose

Realtime, read-only view of the running directional strangle strategy — a backend monitor endpoint
aggregating live indices, grouped legs, Greeks/OI/PCR, P&L totals, status, recent events, and an
indicator matrix, plus the Flutter "Strategy Execution" panel that consumes it. The monitor MUST NOT
mutate strategy state; it is a read path over the running `DirectionalStrangle` instance and the
existing option-chain and indicator-engine caches.
## Requirements
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

The system SHALL include an indicator matrix for the three indices, each active non-hedge
strike, and — for NIFTY — the current at-the-money (ATM) call and put option, spanning
timeframes `5m`, `15m`, `30m`, `1H`, `1D`. For each timeframe it SHALL include EMA(9/20/50/100/
200) on close, three SuperTrend variants — `(10,2)`, `(10,3)`, and `(3,1)` (period, multiplier)
— each with value and direction, Parabolic SAR(0.02/0.02/0.2), RSI(14) with its SMA(14) signal,
and — sourced from the index's current-month futures contract, or from the option's own traded
volume for the ATM CE/PE rows — session VWAP (hlc3) and VWMA(20). Price-based indicators (EMA,
SuperTrend, PSAR, RSI) SHALL be computed on the spot index security id (or the option security id
for ATM rows); volume-anchored VWAP and VWMA SHALL be computed on the futures security id for
index rows (spot indices carry no tradeable volume) and on the option's own 1-minute bars for ATM
rows (options do carry traded volume).

The NIFTY ATM CE/PE rows SHALL resolve the current ATM strike from spot and the nearest expiry,
SHALL compute their indicator values on demand from the `option_bars` 1-minute series (not via a
live per-strike tracker), and SHALL render `null`/`--` for any cell whose backing 1-minute history
is shorter than that indicator's required depth, rather than fabricating a value. ATM CE/PE rows
MUST NOT include Camarilla or previous-period high/low fields (index-only concepts).

The matrix SHALL include Camarilla levels (pp/r3/r4/s3/s4) and previous-period high/low for
three periods — `camarilla_daily` + PDH/PDL, `camarilla_weekly` + PWH/PWL, and
`camarilla_monthly` + PMH/PML — for index rows only. These level sets SHALL be read from the
persisted `index_levels` warehouse (`LevelsStore`) for the current session, NOT recomputed from
the live indicator engine. When a level document is missing the corresponding fields SHALL be
`null` and the endpoint SHALL NOT error. The client maps timeframe to period for display:
`5m`/`15m` use daily, `30m`/`1H` use weekly, `1D` uses monthly.

#### Scenario: Matrix covers indices, active strikes, and NIFTY ATM CE/PE

- **WHEN** the monitor is requested with two short legs open
- **THEN** `indicators` contains entries for NIFTY/BANKNIFTY/SENSEX, the two active non-hedge strike security ids, and a NIFTY ATM CE row and a NIFTY ATM PE row labeled with their resolved strike and expiry

#### Scenario: Matrix includes EMA200, RSI, VWAP and VWMA

- **WHEN** the monitor is requested and warmup has seeded the index and its futures contract
- **THEN** each index timeframe cell includes non-null `ema200`, `rsi`, `rsi_ma`, and — from the futures contract — `vwap` and `vwma`

#### Scenario: Matrix includes three SuperTrend variants

- **WHEN** the monitor is requested for any index or strike timeframe cell
- **THEN** the cell includes three distinct SuperTrend results keyed by variant — `st_10_2`, `st_10_3`, `st_3_1` — each with its own value and direction, computed independently

#### Scenario: ATM CE/PE row indicators computed from option_bars

- **WHEN** the monitor is requested and the NIFTY ATM call's `option_bars` 1-minute series has at least the required depth for a timeframe's EMA/RSI/PSAR/SuperTrend/VWAP/VWMA
- **THEN** that timeframe's cell in the ATM CE row is populated from bars aggregated from `option_bars`, not from the spot IndicatorEngine

#### Scenario: ATM row degrades honestly on short history

- **WHEN** the NIFTY ATM put's `option_bars` 1-minute series has fewer bars than a given indicator's required depth for a timeframe
- **THEN** that indicator's field in the ATM PE row's cell for that timeframe is `null`, not a partial or fabricated value

#### Scenario: ATM rows omit index-only levels

- **WHEN** the monitor is requested and the NIFTY ATM CE/PE rows are present
- **THEN** those rows' cells have no `camarilla_daily`/`camarilla_weekly`/`camarilla_monthly` or `pdh`/`pdl`/`pwh`/`pwl`/`pmh`/`pml` fields populated

#### Scenario: Levels sourced from the warehouse across three periods

- **WHEN** `index_levels` holds daily, weekly, and monthly documents for an index for the current session
- **THEN** that index's `camarilla_daily`/`camarilla_weekly`/`camarilla_monthly` and `period.pdh/pdl/pwh/pwl/pmh/pml` are populated from those documents, and PDH differs from PDL and from the current price

#### Scenario: Missing level document yields nulls, not an error

- **WHEN** the monthly `index_levels` document for an index is absent
- **THEN** `camarilla_monthly` and `period.pmh/pml` are `null` and the endpoint still returns HTTP 200

#### Scenario: 1D column populated after warmup

- **WHEN** the application has completed startup warmup with a 1D data source available
- **THEN** the `1D` row for each index has non-null EMA/SuperTrend/PSAR values rather than `--`

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

