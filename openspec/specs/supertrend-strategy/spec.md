# supertrend-strategy Specification

## Purpose
TBD - created by archiving change add-supertrend-options-strategy. Update Purpose after archive.
## Requirements
### Requirement: Signal-aligned option selling
The strategy SHALL, on each closed signal-timeframe bar, sell an out-of-the-money option of
the nearest weekly expiry aligned with the current SuperTrend direction: short PE when the
trend is up (green), short CE when the trend is down (red). On process restart during the
same trading day, the strategy SHALL recover any open leg from the positions table before
processing bars, so recovered state is treated identically to state built up from live fills.

#### Scenario: Open short PE on uptrend
- **WHEN** there is no open leg and SuperTrend direction is up
- **THEN** the strategy sells the configured OTM PE at the starting lot size

#### Scenario: Open short CE on downtrend
- **WHEN** there is no open leg and SuperTrend direction is down
- **THEN** the strategy sells the configured OTM CE at the starting lot size

#### Scenario: Restart recovers open leg before first bar
- **WHEN** the strategy starts and a non-zero short position tagged to it exists in the positions table for today
- **THEN** `_current` is populated from that position before `on_bar()` is called for the first time, and the strategy does not re-enter the same instrument

### Requirement: Flip closes and reverses
The strategy SHALL, when the SuperTrend direction flips against the open leg, buy back the
open leg and open the opposite-side leg at the starting lot size.

#### Scenario: Up-to-down flip
- **WHEN** a short PE leg is open and SuperTrend flips to down
- **THEN** the strategy buys back the PE and sells the OTM CE at the starting lot size

### Requirement: Scale-in while trend holds
The strategy SHALL add a configured number of lots on each subsequent signal bar while the
SuperTrend direction is unchanged, up to a configured maximum lot count.

#### Scenario: Add a lot on continued trend
- **WHEN** a leg is open, the direction is unchanged on a new bar, and open lots < max
- **THEN** the strategy sells `add_lots` more of the same option

#### Scenario: Respect the max-lots cap
- **WHEN** open lots already equal the maximum
- **THEN** the strategy does not add more lots

### Requirement: Trading window and square-off
The strategy SHALL place no new entries before the configured start time (IST) and SHALL flat
all legs at the configured square-off time (IST), trading no more that day. The start and
square-off times SHALL be compared against the **closed bar's timestamp** (converted to IST),
not against wall-clock time, so live and backtest scheduling are identical and the strategy can
be driven deterministically from historical bars.

#### Scenario: No entries before start
- **WHEN** the current bar's IST timestamp is before the start time
- **THEN** the strategy places no orders

#### Scenario: Square-off at end of window
- **WHEN** the current bar's IST timestamp is at or past the square-off time and a leg is open
- **THEN** the strategy buys back the open leg and stops trading for the day

### Requirement: Paper-only routing
The strategy SHALL route all orders through the platform order router, which is paper unless
live trading is explicitly enabled and a broker is configured.

#### Scenario: Orders route to paper by default
- **WHEN** the strategy places an order and live mode is not enabled
- **THEN** the order is filled by the paper engine

### Requirement: Per-leg stop-loss
The strategy SHALL, on each closed signal bar before evaluating flip or scale-in, compute the
open leg's unrealized mark-to-market loss from its average entry price and the option's latest
price, and SHALL buy back the entire leg at market when that loss reaches or exceeds a
configured per-lot amount multiplied by the current open lot count
(`leg_stop_per_lot × open_lots`). The per-lot amount SHALL be configurable via `params`,
defaulting to 1000. After a stop-driven close the strategy SHALL place no new entry on the same
bar; re-entry is decided by a subsequent bar's signal.

#### Scenario: Leg stop triggers a close
- **WHEN** a leg of `n` lots is open and its unrealized loss reaches `leg_stop_per_lot × n`
- **THEN** the strategy buys back the full leg at market with a `leg_stop` reason and opens no
  new leg on that bar

#### Scenario: Loss below threshold holds the leg
- **WHEN** the open leg's unrealized loss is less than `leg_stop_per_lot × open_lots`
- **THEN** the strategy does not close the leg for stop reasons and proceeds to its normal
  flip / scale-in logic

#### Scenario: Stale or zero option price does not trip the stop
- **WHEN** the option's latest price is unavailable or not greater than zero
- **THEN** the strategy does not evaluate a stop on that bar (no close is forced by a bogus price)

### Requirement: Daily loss cap
The strategy SHALL accumulate realized profit and loss over the trading day and, once cumulative
realized P&L reaches or falls below the negative of a configured cap (`-day_stop`), SHALL flatten
any open leg and place no further entries for the remainder of that session. The cap SHALL be
configurable via `params`, defaulting to 10000. The accumulator SHALL reset at the start of a new
trading day (IST).

#### Scenario: Day cap halts trading
- **WHEN** cumulative realized P&L for the day reaches `-day_stop`
- **THEN** the strategy flattens any open leg and opens no further legs until the next session

#### Scenario: Accumulator resets next day
- **WHEN** a new trading day (IST) begins
- **THEN** the cumulative realized P&L used for the cap resets to zero
