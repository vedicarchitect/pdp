## ADDED Requirements

### Requirement: Enriched terminal leg-close events

Every terminal leg-close event the directional-strangle engine emits SHALL carry the full
round-trip economics. This applies to `leg_close`, `take_profit`, `stop_all`, and the partial
`stop_half`, plus the closes driven by `square_off` / `day_loss_cap`. The carried fields are
`entry_price`,
`exit_price`, `lots`, `entry_time`, `exit_time`, `pnl`, `opt_type`, `strike`, `is_hedge`,
`expiry`, and a resolved human `symbol` (e.g. `NIFTY-Jul2026-24300-CE`). The `pnl` sign
convention SHALL match the engine's own unrealized computation exactly — for a short leg
`pnl = (entry_price − exit_price) × lots × lot_size`, for a hedge/momentum long leg
`pnl = (exit_price − entry_price) × lots × lot_size`. These fields ride the existing daily
JSONL log + OpenSearch sinks; no new persistence store is introduced.

#### Scenario: A short leg close carries entry, exit, and signed P&L

- **WHEN** a short leg opened at premium 100 with 2 lots is bought back at 40 via take-profit
- **THEN** the emitted `take_profit` event carries `entry_price=100`, `exit_price=40`,
  `lots=2`, and `pnl = (100 − 40) × 2 × lot_size` (positive)
- **AND** the event carries the resolved `symbol`, `strike`, `expiry`, and `opt_type`

#### Scenario: A hedge leg close inverts the P&L sign

- **WHEN** a hedge (long) leg is closed
- **THEN** its `pnl` is computed as `(exit_price − entry_price) × lots × lot_size`, the inverse
  of the short convention

#### Scenario: A partial stop closes only half the lots

- **WHEN** a `stop_half` fires on a leg holding N lots
- **THEN** the emitted event closes `N // 2` lots, its `pnl` is computed on the closed lots
  only, and it is marked as a partial so the remaining lots remain open for a later terminal
  close

#### Scenario: Symbol resolution never blocks the tick hot path

- **WHEN** a leg is closed and the human symbol is not already known on the leg
- **THEN** the event is emitted with `symbol=null` rather than performing a blocking DB lookup
  on the tick path, and the symbol is resolved lazily when the trades API is queried

### Requirement: Per-day entry→exit trade ledger derived from events

The system SHALL derive a per-day closed-trades ledger by pairing each `leg_open` with its
terminal close event by `security_id` in time order, from the persisted per-day event stream
(the `logs/<strategy_id>/<date>.log` JSONL, falling back to the `strangle-events` OpenSearch
index). Each paired row SHALL contain `{underlying, security_id, symbol, opt_type, strike,
expiry, lots, is_hedge, entry_price, entry_time, exit_price, exit_time, pnl, reason, partial,
open}`. A still-open leg SHALL appear with null exit fields and `open=true`; a `stop_half`
SHALL produce its own partial row while the remaining lots pair to a later terminal row. No new
Mongo/PG store is created — the ledger is a read-time pairing over existing events.

#### Scenario: A clean round-trip pairs open to take-profit

- **WHEN** the day's events contain a `leg_open` for a security followed by its `take_profit`
- **THEN** the ledger returns one row with matching entry/exit prices, times, and `pnl`, and
  `open=false`

#### Scenario: A stop-half then stop-all yields a partial plus a terminal row

- **WHEN** a leg is opened, then a `stop_half` closes half its lots, then a `stop_all` closes
  the rest
- **THEN** the ledger returns a partial row (`partial=true`) for the half and a terminal row
  for the remaining lots, and no lots are double-counted

#### Scenario: A still-open leg is returned as open

- **WHEN** a `leg_open` has no terminal close event yet on the queried day
- **THEN** the ledger returns that leg with `exit_price=null`, `exit_time=null`, `pnl=null`,
  and `open=true`

### Requirement: Closed-trades API grouped by index

The system SHALL expose `GET /api/v1/strangle/trades?strategy_id=&date=` returning the paired
round-trip rows grouped by index — `{date, by_index: {NIFTY: [...], BANKNIFTY: [...],
SENSEX: [...]}, totals: {realized_pnl, n_round_trips, n_open}}`. `date` SHALL default to today
IST and `strategy_id` SHALL default to all running strangle strategies. `realized_pnl` in
`totals` SHALL be the sum of `pnl` over closed rows only — open legs contribute zero. Rows with
an unresolved `symbol` SHALL be resolved lazily before the response is returned.

#### Scenario: Trades are grouped per index and never blended

- **WHEN** the trades API is queried for a day with NIFTY, BANKNIFTY, and SENSEX activity
- **THEN** the response groups rows under `by_index` keyed by underlying, with no cross-index
  blending

#### Scenario: Realized total excludes open legs

- **WHEN** the day has two closed round-trips and one still-open leg
- **THEN** `totals.realized_pnl` sums only the two closed rows' `pnl` and `totals.n_open` is 1

### Requirement: Canonical per-index live P&L

The engine `state()` SHALL be the single authority for live P&L (`day_realized`,
`day_unrealized`, `day_pnl`) and SHALL carry its `underlying`. The system SHALL expose a
per-index P&L breakdown (via `GET /api/v1/strangle/pnl` or an extended `/strangle/stats`)
returning `[{underlying, day_realized, day_unrealized, day_pnl, n_open_legs, done_for_day,
squared_off_at}]` plus a `totals` object. This SHALL be the only P&L source the dashboard
portfolio card and the Execution tab read; the journal's `compute_daily_stats` SHALL NOT be a
live-P&L source.

#### Scenario: Per-index P&L reconciles with the trade ledger

- **WHEN** the per-index P&L is fetched for a day after square-off
- **THEN** each index's realized component reconciles with the sum of that index's closed-row
  `pnl` from the trade ledger for the same day

#### Scenario: Squared-off time is reported per index

- **WHEN** an index's strategy has emitted a terminal `square_off`/`day_loss_cap`
- **THEN** that index's `done_for_day` is true and `squared_off_at` is the IST time of the
  terminal event, else `squared_off_at` is null
