## ADDED Requirements

### Requirement: Config-driven multi-day simulation engine
The system SHALL provide an importable `simulate_day(config, trade_date, data)` engine (in
`src/pdp/backtest/sim.py`) that runs the SuperTrend option-selling logic for one trade day driven
entirely by a `StrategyConfig`. The engine SHALL read no module-level strategy constants; all knobs
(SuperTrend period/multiplier, timeframe, moneyness, lots, session times, stops, roll) SHALL come
from the config. `backtest_multiday.py` SHALL build a config from its values and call this engine.

#### Scenario: Engine consumes config
- **WHEN** `simulate_day` is called with two configs differing only in `st_period`
- **THEN** each run uses its own SuperTrend period and produces independent results

#### Scenario: Legacy config preserves baseline
- **WHEN** the engine runs the full historical window with the legacy config
- **THEN** the window net P&L equals the pre-refactor `backtest_multiday.py` baseline

### Requirement: Signed moneyness strike selection
The engine SHALL select the option strike from spot using a signed `moneyness` offset:
`atm = round(spot/step)*step`; for CE the strike SHALL be `atm + moneyness*step` and for PE
`atm - moneyness*step`, so `moneyness > 0` is OTM, `0` is ATM, and `< 0` is ITM. The result SHALL
feed the existing nearest-strike warehouse fallback unchanged.

#### Scenario: OTM selection
- **WHEN** `select_strike(spot, "CE", moneyness=2, step=50)` is called
- **THEN** it returns the strike two steps above ATM

#### Scenario: ITM selection
- **WHEN** `select_strike(spot, "PE", moneyness=-1, step=50)` is called
- **THEN** it returns the strike one step above ATM (in-the-money for a put)

#### Scenario: ATM selection
- **WHEN** `select_strike(spot, "CE", moneyness=0, step=50)` is called
- **THEN** it returns the ATM strike

### Requirement: First-flip base-lot entry
The engine SHALL open the first position of the day only on the first genuine SuperTrend flip after
session start, sizing the entry at `config.base_lots`.

#### Scenario: No entry before first flip
- **WHEN** the session has started but no SuperTrend flip has occurred yet
- **THEN** the engine opens no position

#### Scenario: Base-lot entry on first flip
- **WHEN** the first genuine flip occurs after session start
- **THEN** the engine opens a `base_lots` short position on the trend-aligned option side

### Requirement: Option-premium scale-in gate
The engine SHALL add `config.add_lots` to the active leg only when the current option bar's low
breaks below the prior option bar's low (premium decay continuing in our favour), never exceeding
`config.max_lots`.

#### Scenario: Add when premium makes a new low
- **WHEN** the active leg's current option bar low is below the prior bar's low and lots < max
- **THEN** the engine adds `add_lots`

#### Scenario: Defer when premium does not make a new low
- **WHEN** the current option bar's low is at or above the prior bar's low
- **THEN** the engine adds nothing this bar and re-evaluates on the next bar

#### Scenario: Respect max lots
- **WHEN** the active leg is already at `max_lots`
- **THEN** the engine adds nothing regardless of the premium break

### Requirement: Partial-flip strangle with flip-candle-break resolution
On a SuperTrend direction flip the engine SHALL close all additional legs of the old side, keep the
old side's base leg, open the opposite side's base leg, and record the flip candle's high and low.
The engine SHALL then resolve the resulting two-base-leg strangle by flip-candle extreme break:
close the old-side base leg when NIFTY breaks above the flip candle's high, and close the new-side
base leg when NIFTY breaks below the flip candle's low. End-of-day square-off SHALL flatten all legs.

#### Scenario: Flip keeps old base and opens opposite base
- **WHEN** direction flips while the active leg holds base + additional lots
- **THEN** the additional lots are closed, the base leg is retained, and an opposite-side base leg is
  opened, leaving a two-leg strangle

#### Scenario: Old base closes on flip-high break
- **WHEN** in a strangle and NIFTY trades above the recorded flip-candle high
- **THEN** the old-side base leg is closed and the new-side base leg continues

#### Scenario: New base closes on flip-low break
- **WHEN** in a strangle and NIFTY trades below the recorded flip-candle low
- **THEN** the new-side base leg is closed and the old-side base leg continues

#### Scenario: Square-off flattens the strangle
- **WHEN** the square-off time is reached while a strangle is open
- **THEN** all open legs are closed

### Requirement: Configurable exit toggles
Roll-up on premium decay, the per-leg MTM stop, and the daily loss cap SHALL be configurable via
`StrategyConfig` (`roll_enabled`/`roll_trigger_prem`/`roll_target_min_prem`, `leg_stop_per_lot`,
`day_stop`).

#### Scenario: Roll-up disabled
- **WHEN** `roll_enabled` is false and a leg's premium falls below `roll_trigger_prem`
- **THEN** the engine does not roll the leg

#### Scenario: Day stop honoured
- **WHEN** cumulative realized day loss reaches `day_stop`
- **THEN** the engine flattens open legs and makes no further entries that day

### Requirement: New engine excludes profit-lock and ST-touch exits
The config-driven `simulate_day` engine SHALL NOT implement the trailing profit-lock or ST-touch
intra-bar exit. These remain defined only for the live strategy (`supertrend-strategy` spec) and are
out of scope for the swept backtest strategy, which acts on completed bars plus the
flip-candle-break rule. `StrategyConfig` SHALL expose no fields for them.

#### Scenario: No profit-lock in the engine
- **WHEN** a leg's MTM peaks and then retraces during a `simulate_day` run
- **THEN** the engine does not close the leg for a profit-lock reason (only stops, flip, roll,
  strangle break, or square-off can close it)

#### Scenario: No intra-bar ST-touch in the engine
- **WHEN** intra-bar NIFTY prices touch the SuperTrend line during a bar
- **THEN** the engine takes no intra-bar exit; exits are evaluated on completed bars and the
  flip-candle-break rule
