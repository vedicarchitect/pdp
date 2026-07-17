## MODIFIED Requirements

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

Within each of the following independent groups, the endpoint SHALL issue the underlying async I/O
concurrently (e.g. via `asyncio.gather`) rather than serially awaiting one item at a time, since no
item in a group depends on another: (a) per-index spot/future LTP and spot age across
NIFTY/BANKNIFTY/SENSEX; (b) per-leg Greeks/OI/PCR lookups across open legs; (c) per-`(security_id,
timeframe)` indicator matrix cells; (d) the NIFTY ATM CE and PE row builds. This is a latency
requirement only — the response content and field values MUST be identical to the sequential form.

#### Scenario: Monitor returns full snapshot when strangle running

- **WHEN** a `DirectionalStrangle` is running and `GET /api/v1/strangle/monitor` is called
- **THEN** the response is HTTP 200 with `indices`, `groups`, `totals`, `status`, `recent_events`, and `indicators` keys populated

#### Scenario: Monitor 404 when no strangle

- **WHEN** no `DirectionalStrangle` instance is running and the endpoint is called
- **THEN** the response is HTTP 404

#### Scenario: Future LTP null when futures sid unset

- **WHEN** the running strategy has no `futures_security_id` configured
- **THEN** the corresponding index `future` field is `null` while `spot` is still populated

#### Scenario: Independent I/O groups run concurrently

- **WHEN** the monitor builds the indices block, the per-leg Greeks, the indicator matrix, or the
  ATM CE/PE rows
- **THEN** each item within that group is fetched via a single concurrent gather rather than one
  sequential await per item, and the resulting payload values are unchanged from the sequential form
