# supertrend-strategy

## ADDED Requirements

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
