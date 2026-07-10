# execution-console-daily-parity Specification

## Purpose

Ensures the live execution console shows the same positions and trades every day as what actually
happened, by closing three independent root causes of drift: phantom P&L from a zero `entry_price`,
lost PostgreSQL cost basis on reopen/reversal, and in-memory strategy legs that vanish on restart.
It also makes the daily trade ledger DB-first (not local-file-based), keeps the Live broker account
view fresh intraday instead of only at the 15:45 IST EOD sync, and reconciles the three independent
views of "my positions" — the strategy's in-memory legs, the PostgreSQL position ledger, and the
broker's reported positions — emitting a CRITICAL event when they diverge.

## Requirements

### Requirement: Open legs SHALL never carry a zero entry price

A strategy SHALL never record an open leg with a zero or missing `entry_price`. When the fill
average price cannot be resolved from the broker within the fill-wait window, the strategy SHALL
resolve a real reference price (cached LTP → chain LTP → last bar close) or, if none is available,
abort and square the leg and emit a CRITICAL event — rather than storing `entry_price = 0`.

#### Scenario: Cold LTP cache at open does not produce phantom P&L

- **WHEN** a leg is opened on a freshly-subscribed option whose `ltp:` cache has no tick yet and the broker fill price is unresolved
- **THEN** the leg's `entry_price` is set from a real reference price, or the leg is squared and a CRITICAL `MISSING_LTP` event is emitted, and the console never shows the leg with `entry —` or an MTM equal to `-ltp × qty`

#### Scenario: MTM is computed only against a real entry price

- **WHEN** the execution console computes a leg's MTM
- **THEN** it uses a non-zero recorded `entry_price`, so day P&L and the hard-cap auto-kill are never driven by a phantom `-ltp × qty` loss

### Requirement: Position cost basis SHALL be re-based on reopen and reversal

`upsert_position` SHALL, after booking realized P&L on the closed quantity, set the residual/new
position's `avg_price` to the incoming fill price whenever the fill opens the position from flat
(previous `net_qty` was zero) or reverses it through zero, so PostgreSQL never carries a zero or
stale cost basis for a position whose `net_qty` is non-zero.

#### Scenario: Reopening a flattened position sets a fresh cost basis

- **WHEN** a position row that was flattened to `net_qty = 0, avg_price = 0` receives a new fill
- **THEN** its `avg_price` is set to the new fill price (not left at `0`), so `/api/v1/positions` and leg rehydration show a real entry

#### Scenario: A single fill reversing through zero re-bases cost basis

- **WHEN** one fill takes a position from long to short (or short to long) through zero
- **THEN** realized P&L is booked on the closed quantity and the residual leg's `avg_price` is set to the fill price, not the prior side's cost basis

### Requirement: Strategy open legs SHALL be rehydrated on restart

On startup a strategy SHALL reconstruct its open legs (shorts, hedges, momentum) from the durable
position ledger (PostgreSQL positions plus the last `leg_open` events), with correct
`entry_price`, lots, strike, and hedge/momentum classification, so the execution console reflects
the true open positions after an intraday restart rather than an empty in-memory list.

#### Scenario: Console still shows open legs after an intraday restart

- **WHEN** the engine restarts mid-session while legs are open in PostgreSQL and at the broker
- **THEN** the strategy rehydrates those legs and `/strangle/legs` + `/strangle/monitor` show them with their original entry prices, not "no open legs"

### Requirement: The daily trade ledger SHALL be derived from a durable store

The per-day entry→exit trade ledger SHALL be built from a durable store — PostgreSQL `trades`
joined to the persisted `leg_open`/`leg_close` event stream — not from local JSONL log files, so
the execution tab shows every trade for the day regardless of process restarts or working
directory. A local-file read MAY remain only as a last-resort fallback.

#### Scenario: Ledger is complete after a restart

- **WHEN** `/api/v1/strangle/trades` is requested after the process restarted or ran under a different working directory earlier in the day
- **THEN** the ledger includes every round-trip and open leg for the day, read from the durable store, and does not silently return an empty list

### Requirement: The live broker account view SHALL refresh intraday

The Live broker (Dhan) account view SHALL reflect intraday holdings, positions, and funds by
refreshing the mirror during market hours at a configurable interval — not only at the 15:45 IST
EOD sync — and SHALL expose a `last_synced_at` timestamp so the UI can indicate staleness. Refresh
SHALL be a paper-safe no-op when live credentials are absent.

#### Scenario: A manual Dhan position appears intraday

- **WHEN** a position is opened directly in the Dhan terminal at 11:00 IST
- **THEN** it appears in the Live account tab within one refresh interval, and the tab shows a `last_synced_at` time

#### Scenario: Stale data is visibly flagged

- **WHEN** the last successful broker-account refresh is older than the staleness threshold
- **THEN** the Live account tab shows a stale indicator rather than presenting old holdings/positions as current

### Requirement: Positions SHALL be reconciled across the three views

The system SHALL reconcile the strategy's in-memory legs, the PostgreSQL position ledger, and the
broker's reported positions, and SHALL emit a CRITICAL `POSITION_RECONCILE_MISMATCH` event when
they diverge beyond a configurable tolerance (a leg with no matching broker position, a broker
position with no matching leg, or a net-quantity/side mismatch).

#### Scenario: A leg that never filled is surfaced

- **WHEN** the strategy holds an in-memory short leg but the broker reports no matching position
- **THEN** a CRITICAL `POSITION_RECONCILE_MISMATCH` event is emitted naming the security and the divergence

#### Scenario: A manual broker trade is surfaced

- **WHEN** the broker reports a position that no running strategy leg accounts for
- **THEN** a CRITICAL `POSITION_RECONCILE_MISMATCH` event is emitted so the untracked position is visible
