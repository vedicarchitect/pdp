## ADDED Requirements

### Requirement: Fixed actual-strike option pricing

The backtest SHALL price option legs from the `option_bars` warehouse by the **fixed actual
contract** — `(underlying, expiry_date, strike, option_type, timeframe)` — rather than an
ATM-relative rolling label. The target strike SHALL be derived from spot (ATM rounded to the strike
grid, plus the strategy's OTM offset) and the `expiry_date` from the NIFTY expiry calendar. When the
exact target strike is unavailable for a day, the backtest SHALL fall back to the **nearest
available strike** within the warehoused band before any live API call. A held position SHALL be
priced as one stable fixed-strike series across the days it is held.

#### Scenario: Leg priced from the fixed contract

- **WHEN** the backtest needs an option price for a given trade day and side
- **THEN** it computes the target strike from spot and resolves `expiry_date` from the calendar
- **AND** reads that exact `(expiry_date, strike, option_type)` series from `option_bars`, resampled
  to the signal timeframe

#### Scenario: Nearest-strike fallback

- **WHEN** the exact target strike has no bars for the day but other band strikes do
- **THEN** the backtest prices from the nearest available strike and logs the substitution

#### Scenario: Positional hold reads one series

- **WHEN** a position is held across multiple days
- **THEN** the same fixed `(expiry_date, strike, option_type)` contract is read for every day of the
  hold, without strike drift
